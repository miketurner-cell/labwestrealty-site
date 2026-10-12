/**
 * chat.ts — "Turner Assistant" AI chatbot backend, Lab West (sites, D-1012-34, component 9).
 *
 * Port of goosebayrealestate-site/netlify/functions/chat.ts with the Lab West config only: Labrador City and Wabush, Mike Turner,
 * Broker of Record, as the one contact (no agents, no office address), SITE labwestrealty.com, origin allow-list for this site.
 * Kept zero-npm-import like the original.
 *
 * DARK: while no generated listings data is bundled (tools/idx-cache/listings-projected.json, written only by the gated rebuild
 * when LABWEST_LISTINGS is preview or on) the function answers 404 to everyone, so it is indistinguishable from a missing page.
 * The widget (js/chat-widget.js) is only emitted into generated pages. Secrets it needs (names only): ANTHROPIC_API_KEY,
 * SUPABASE_URL, SUPABASE_SERVICE_KEY, POSTMARK_OFFICE_INBOX (optional). Without them it fails closed.
 * Leads post server-side to Gander's lead-receive with referer https://labwestrealty.com (routing is lead's, D-1012-33).
 */

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || "";
const SUPABASE_URL = process.env.SUPABASE_URL || "";
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY || "";

// Voice on the Turner Assistant (Ship 5 port, 2026-09-12 -- Gander canary
// 2026-09-10, ~/.claude/plans/now-that-we-have-polymorphic-wolf.md).
// CHAT_VOICE=on since 2026-09-12 (Netlify, context production). Confirmed
// live the same day: a bare env-var write does NOT take effect until the
// next real deploy touches a non-tools/.github path (this site's own
// netlify.toml [build].ignore, Conv #122, skips tools/.github-only
// commits) -- this comment IS that deploy. Verified after with a direct
// curl of mode:"tts" (200, audio/mpeg), not just a stored-value readback.
const CHAT_VOICE_MODE = (process.env.CHAT_VOICE || "off").trim().toLowerCase();
const ELEVENLABS_API_KEY = process.env.ELEVENLABS_API_KEY || "";
const REEL_VOICE_ID = process.env.REEL_VOICE_ID || "";
// check_rate_limit only counts REQUESTS in a fixed window, not an arbitrary
// summed quantity -- there is no "sum of characters this month" primitive
// available to a stateless serverless function. CHAT_TTS_MONTHLY_CAP is
// therefore a request-count cap, sized as an approximation of the plan's
// literal "20k chars/month" figure against a ~400-char typical reply
// (20000/400=50).
const CHAT_TTS_MONTHLY_CAP = parseInt(process.env.CHAT_TTS_MONTHLY_CAP || "50", 10) || 50;
const MAX_TTS_CHARS = 600; // a spoken chat reply is a short answer, not a monologue
const MAX_TRANSCRIBE_AUDIO_BYTES = 6 * 1024 * 1024; // ~20s at typical webm/opus bitrates, generous headroom

// ── Rate limiting (security hardening 2026-08-22) ───────────────────────
// Supabase-backed fixed-window limiter (check_rate_limit RPC, service-role only).
// Fail-OPEN on any error so a Supabase blip never blocks a legit visitor.
async function rateOk(bucket: string, max: number, windowSec: number, opts?: { failClosed?: boolean }): Promise<boolean> {
  const onErrorResult = !opts?.failClosed;
  limiterDown = false;
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) { limiterDown = true; return onErrorResult; }
  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/check_rate_limit`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_SERVICE_KEY,
        Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_bucket: bucket, p_max: max, p_window_seconds: windowSec }),
    });
    if (!r.ok) { limiterDown = true; return onErrorResult; }
    return (await r.json()) === true;
  } catch {
    { limiterDown = true; return onErrorResult; }
  }
}
function clientIp(event: any): string {
  const h = event.headers || {};
  return String(
    h["x-nf-client-connection-ip"] ||
      (h["x-forwarded-for"] || "").split(",")[0].trim() ||
      "unknown",
  ).slice(0, 64);
}

// ── Voice: Scribe transcription (Ship 5 port) ───────────────────────────
// Mirrors tools/_eleven.py:stt()'s multipart construction exactly (same
// vendor endpoint, same field names) -- kept as its own small function
// here rather than a shared cross-language module since Netlify Functions
// can't import a Python file, and the request is simple enough that
// duplicating ~20 lines beats adding an HTTP hop to a second function.
async function scribeTranscribe(audioBuf: Buffer, mimeType: string): Promise<{ ok: boolean; text?: string; reason?: string }> {
  if (!ELEVENLABS_API_KEY) return { ok: false, reason: "unconfigured" };
  const boundary = `----turnerChatVoice${Date.now()}${Math.random().toString(16).slice(2)}`;
  const ext = mimeType.includes("webm") ? "webm" : mimeType.includes("mp4") || mimeType.includes("m4a") ? "m4a" : "ogg";
  const parts: Buffer[] = [
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\nscribe_v2\r\n`, "utf8"),
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.${ext}"\r\nContent-Type: ${mimeType}\r\n\r\n`, "utf8"),
    audioBuf,
    Buffer.from(`\r\n--${boundary}--\r\n`, "utf8"),
  ];
  const body = Buffer.concat(parts);
  try {
    const r = await fetch("https://api.elevenlabs.io/v1/speech-to-text", {
      method: "POST",
      headers: { "xi-api-key": ELEVENLABS_API_KEY, "Content-Type": `multipart/form-data; boundary=${boundary}` },
      body: body as unknown as BodyInit,
    });
    if (!r.ok) return { ok: false, reason: `HTTP ${r.status}` };
    const data = await r.json();
    const text = (data && data.text) || "";
    if (!text.trim()) return { ok: false, reason: "empty transcript" };
    return { ok: true, text };
  } catch (e: any) {
    return { ok: false, reason: e?.message || "network error" };
  }
}

// ── Voice: TTS for a chat reply (Ship 5 port) ───────────────────────────
// Deliberately does NOT cache to R2 the way listing-audio.ts does -- each
// chat reply is unique conversational text with no reuse value, so caching
// would only cost storage for zero benefit. The audio streams straight back
// in the HTTP response (base64, isBase64Encoded) and is never persisted
// anywhere.
async function ttsReply(text: string): Promise<{ ok: boolean; audioB64?: string; reason?: string }> {
  if (!ELEVENLABS_API_KEY || !REEL_VOICE_ID) return { ok: false, reason: "unconfigured" };
  try {
    const r = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${REEL_VOICE_ID}`, {
      method: "POST",
      headers: { "xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json", Accept: "audio/mpeg" },
      body: JSON.stringify({
        text,
        model_id: "eleven_flash_v2_5",
        voice_settings: { stability: 0.5, similarity_boost: 0.75 },
      }),
    });
    if (!r.ok) return { ok: false, reason: `HTTP ${r.status}` };
    const buf = Buffer.from(await r.arrayBuffer());
    if (!buf.length) return { ok: false, reason: "empty audio" };
    return { ok: true, audioB64: buf.toString("base64") };
  } catch (e: any) {
    return { ok: false, reason: e?.message || "network error" };
  }
}
// Used only in SYSTEM_PROMPT's office contact line — capture_lead itself no
// longer emails this inbox directly (2026-08-22).
const OFFICE_INBOX = process.env.POSTMARK_OFFICE_INBOX || "miketurner@royallepage.ca";

const SITE = "https://labwestrealty.com";
const MODEL = "claude-haiku-5-5";
// D-1008-97 (Mike 2026-10-08: "Haiku 5.5 is now out, so we need to update to 5.5"). Haiku 5.5 thinks
// adaptively by default and thinking tokens count toward max_tokens; a live chat wants speed, so effort is
// "low" (the model can skip thinking on simple turns). No temperature/top_p/top_k and no prefill on 5.5.
const EFFORT = "low";

const PARSE_TOOL = {
  name: "set_search_filters",
  description: "Translate the visitor's natural-language home search into structured filters.",
  input_schema: {
    type: "object",
    properties: {
      city: { type: "string", description: "Town/community mentioned, e.g. 'Gander'. Omit if none." },
      mls_number: { type: "string", description: "If the query IS an MLS number (6-8 digits), put it here and nothing else." },
      price_min: { type: "number" },
      price_max: { type: "number" },
      beds_min: { type: "number" },
      baths_min: { type: "number" },
      ptypes: {
        type: "array", items: { type: "string", enum: ["Residential", "Land", "Commercial", "Multi-Family"] },
        description: "Property types implied (house/home/bungalow→Residential; lot/acreage→Land).",
      },
      waterfront: { type: "boolean" },
      ocean_view: { type: "boolean" },
      cottage: { type: "boolean", description: "Cabin/cottage country intent." },
      new_construction: { type: "boolean" },
      just_listed: { type: "boolean", description: "Newly listed / this week." },
      price_drop: { type: "boolean", description: "Reduced / price improved." },
    },
  },
};
const MAX_TURNS = 24; // hard server cap on history length

// ── Mike Turner, Broker of Record (the one contact on this site, D-1012-28) ─────
const AGENTS = [
  {
    name: "Mike Turner",
    phone: "709-256-7999",
    email: "miketurner@royallepage.ca",
    title: "Broker of Record, Royal LePage Turner Realty",
    profile: `${SITE}/about-turner.html`,
  },
];

// ── System prompt (cached via cache_control) ────────────────────────────
const SYSTEM_PROMPT = `TERMINOLOGY: "VOW" stands for "Virtual Office Website" (the registered-access rules for sold data). Never expand the acronym any other way; usually just say "sold prices require a free registered account."\nYou are Turner Assistant, the AI assistant on labwestrealty.com, the Labrador West website of Royal LePage Turner Realty (est. 1998). There is no Turner office and no Turner agent in Labrador West yet: the contact for every inquiry is Mike Turner, Broker of Record, 709-256-7999, ${OFFICE_INBOX}. Never give a street address for a Lab West office; there is none.

Your job: help home buyers and sellers in Labrador City and Wabush (Labrador West). You can search live listings, share market statistics, connect visitors with Mike Turner, and take messages.

HARD RULES — never break these:
1. NEVER invent listings, prices, addresses, statistics, or names. Only present what your tools return. If a tool returns nothing, say so honestly.
2. Sold prices are PRIVATE in Newfoundland & Labrador (VOW rules). You may share aggregate market stats (sales counts, days on market) from your market_stats tool, but NEVER an individual property's sold price. When asked what a specific property sold for, explain that sold prices are free to view with a registered account and link to ${SITE}/listings/sold/.
3. When a visitor shows buying/selling intent or asks to talk to someone, offer to take their name + email (and phone if offered) via capture_lead — but FIRST ask "Is it OK to have Mike Turner contact you about this?" (consent is required).
3a. If a visitor asks about joining Royal LePage Turner Realty as a REALTOR® (careers, recruiting, switching brokerages, getting licensed), say we'd be glad to talk and offer to pass their name + email (and phone if offered) to our broker, Mike Turner, in confidence. FIRST ask "Is it OK for our broker, Mike Turner, to contact you about this?", then call capture_lead with recruiting: true. Never ask for licence numbers or other personal details.
4. Stay on real estate and this brokerage. Politely decline anything else (no poems, code, politics, other businesses).
5. You are an AI. If asked, say so. Never claim to be a human agent.
6. Keep answers short and conversational — 1-3 sentences plus a listing list when relevant. Always format listing links as full URLs.
7. Listing data refreshes regularly and every answer comes from the live feed; sold statistics cover roughly the last two years.
8. If a visitor asks about Central Newfoundland (Gander area), point them to https://realestategander.com. For St. John's / the Avalon Peninsula, point them to https://avalonrealestate.ca. For Happy Valley-Goose Bay, point them to https://goosebayrealestate.ca. Same brokerage, dedicated local teams.

When listing results, show at most 5: street address, city, price, beds/baths if present, and the full URL. If more matched, say how many more and suggest narrowing or browsing ${SITE}/listings/.
search_listings returns Active homes only. When its also_conditionally_sold is above 0, add one short line after the list: "N more are conditionally sold." (use the number; don't list them, and don't call them available).`;

// ── Tool definitions ─────────────────────────────────────────────────────
const TOOLS = [
  {
    name: "search_listings",
    description:
      "Search the live active MLS listings on labwestrealty.com (Labrador City + Wabush, Labrador West). Returns up to 12 matches. Returns Active homes only, plus also_conditionally_sold: how many conditionally sold homes match the same filters.",
    input_schema: {
      type: "object",
      properties: {
        city: { type: "string", description: "Town/community name, e.g. 'Labrador City', 'Wabush'. Optional." },
        price_max: { type: "number", description: "Maximum list price in CAD. Optional." },
        price_min: { type: "number", description: "Minimum list price in CAD. Optional." },
        beds_min: { type: "number", description: "Minimum bedrooms. Optional." },
        property_type: {
          type: "string",
          enum: ["Residential", "Land", "Commercial", "Multi-Family"],
          description: "Optional property type filter.",
        },
        waterfront: { type: "boolean", description: "Only waterfront properties. Optional." },
      },
    },
  },
  {
    name: "market_stats",
    description:
      "Aggregate sold-market statistics for a Labrador West community over ~the last 2 years: sales count, median sold price, median days on market. AGGREGATES ONLY — never returns individual sold prices.",
    input_schema: {
      type: "object",
      properties: { city: { type: "string", description: "Community name, e.g. 'Labrador City' or 'Wabush'." } },
      required: ["city"],
    },
  },
  {
    name: "find_agent",
    description:
      "Find the Royal LePage Turner Realty contact who covers a given community. Returns name, phone, email, profile URL. Labrador West = Mike Turner, Broker of Record; Central NL and the Avalon route to sibling Turner sites.",
    input_schema: {
      type: "object",
      properties: { community: { type: "string", description: "Community name, e.g. 'Labrador City', 'Gander', 'St. John's'." } },
      required: ["community"],
    },
  },
  {
    name: "capture_lead",
    description:
      "Save a visitor's contact request so Mike Turner follows up. Only call AFTER the visitor has provided contact info AND agreed to be contacted.",
    input_schema: {
      type: "object",
      properties: {
        name: { type: "string" },
        email: { type: "string" },
        phone: { type: "string", description: "Optional." },
        interest: { type: "string", description: "What they want (property address, buying/selling intent, question)." },
        community: { type: "string", description: "Community of interest if known. Optional." },
        agent_requested: { type: "string", description: "Leave unset on Lab West: Mike Turner is the only contact." },
        mls: { type: "string", description: "MLS number, if the lead is about one specific listing. Optional." },
        recruiting: { type: "boolean", description: "true ONLY when the visitor is asking about joining the brokerage as a REALTOR® (a recruiting inquiry, not a buyer or seller). It goes to the broker, Mike Turner." },
      },
      required: ["name", "email", "interest"],
    },
  },
  {
    name: "get_listing_details",
    description:
      "Full details for ONE active listing by MLS number (taxes, heating, lot, year built, remarks — everything on its listing page). Use when the visitor asks about a specific property.",
    input_schema: {
      type: "object",
      properties: { mls: { type: "string", description: "The MLS number, e.g. '1296014'." } },
      required: ["mls"],
    },
  },
];

// ── Tool implementations ─────────────────────────────────────────────────
const norm = (s: string) => (s || "").toLowerCase().replace(/[^a-z]/g, "");
const WATERFRONT_RE = /waterfront|ocean ?front|lake ?front|river ?front|water frontage|on the water|on the lake|on the river/i;

// Site review (2026-09-29): the raw projected cache (/tools/idx-cache/listings-projected.json)
// is no longer served publicly. The assistant reads the copy bundled into this function
// (netlify.toml [functions.chat] included_files).
async function readActiveBundle(): Promise<any | null> {
  try {
    const fs = await import("node:fs");
    const path = await import("node:path");
    for (const base of [process.cwd(), "/var/task", path.join(__dirname, "..", ".."), path.join(__dirname, "..", "..", "..")]) {
      const p = path.join(base, "tools/idx-cache/listings-projected.json");
      if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf8"));
    }
  } catch { /* fall through */ }
  return null;
}

async function searchListings(input: any): Promise<any> {
  // Goosebay active feed: DDF-shape projection {listings:[…]} — fields
  // verified live 2026-06-12: city_raw/city_slug, property_type/_subtype,
  // url_path, list_price, bedrooms, bathrooms. No waterfront flag → remarks regex.
  const data = await readActiveBundle();
  if (!data) return { error: "listings feed unavailable (bundle)" };
  const rows: any[] = data.listings || data.rows || [];
  const cityN = norm(input.city || "");
  // D-1011-04 (see the Gander copy): Active only; conditionally sold matches are counted, firm-sold pending left out.
  const isActive = (l: any) => !l.status || l.status === "Active";
  const isCond = (l: any) => /^cond/i.test(String(l.status || ""));
  const matches = (l: any) => {
    if (cityN && !norm(l.city_raw || "").includes(cityN) && !norm(l.city_slug || "").includes(cityN)) return false;
    const p = Number(l.list_price || 0);
    if (input.price_max && (!p || p > input.price_max)) return false;
    if (input.price_min && (!p || p < input.price_min)) return false;
    if (input.beds_min && Number(l.bedrooms || 0) < input.beds_min) return false;
    if (input.property_type) {
      const pt = `${l.property_type || ""} ${l.property_subtype || ""}`.toLowerCase();
      if (!pt.includes(String(input.property_type).toLowerCase().split("-")[0])) return false;
    }
    if (input.waterfront && !WATERFRONT_RE.test(l.public_remarks || "")) return false;
    return true;
  };
  let out = rows.filter((l) => isActive(l) && matches(l));
  const condCount = rows.filter((l) => isCond(l) && matches(l)).length;
  const total = out.length;
  out = out.sort((a, b) => (b.list_date || "").localeCompare(a.list_date || "")).slice(0, 12);
  return {
    total_matches: total,
    showing: out.length,
    also_conditionally_sold: condCount,
    listings: out.map((l) => ({
      address: l.street,
      city: l.city_raw || "Labrador City",
      price: l.list_price,
      beds: l.bedrooms,
      baths: l.bathrooms,
      type: l.property_type,
      url: `${SITE}${l.url_path || ""}`,
      mls: l.mls,
    })),
  };
}

async function marketStats(input: any): Promise<any> {
  // Sold AGGREGATES computed server-side from the sold feed. Individual rows
  // (and their close prices) never leave this function.
  // Site review item 3 (2026-09-29): the public URL now needs a signed-in user,
  // so read the copy bundled into this function (netlify.toml included_files).
  let data: any = null;
  try {
    const fs = await import("node:fs");
    const path = await import("node:path");
    for (const base of [process.cwd(), "/var/task", path.join(__dirname, "..", ".."), path.join(__dirname, "..", "..", "..")]) {
      const p = path.join(base, "listings/sold/data.json");
      if (fs.existsSync(p)) { data = JSON.parse(fs.readFileSync(p, "utf8")); break; }
    }
  } catch { data = null; }
  if (!data) return { error: "sold feed unavailable (bundle)" };
  const rows: any[] = data.rows || [];
  const cityN = norm(input.city || "");
  const subset = rows.filter((r) => {
    const c = norm(r.city || "");
    return cityN && (c.includes(cityN) || cityN.includes(c) || (cityN === "labwest" || cityN === "labradorwest") && (c.includes("labradorcity") || c.includes("wabush")));
  });
  if (!subset.length) return { city: input.city, sales_last_2yr: 0, note: "No recorded sales for that community in the last ~2 years." };
  const prices = subset.map((r) => Number(r.close_price || 0)).filter((p) => p > 0).sort((a, b) => a - b);
  const doms = subset.map((r) => Number(r.dom || 0)).filter((d) => d > 0).sort((a, b) => a - b);
  const med = (arr: number[]) => (arr.length ? arr[Math.floor(arr.length / 2)] : null);
  return {
    city: subset[0].city,
    window: "~last 2 years",
    sales_last_2yr: subset.length,
    ...(prices.length ? { median_sold_price: med(prices) } : {}),
    median_days_on_market: med(doms),
    note: "Aggregates only. Individual sold prices are viewable free with a registered account at " + SITE + "/listings/sold/",
  };
}

const CENTRAL_NL = ["gander", "lewisporte", "twillingate", "glovertown", "gambo", "appleton", "glenwood", "eastport", "musgraveharbour", "carmanville", "dover", "harebay", "newwesvalley"];
const AVALON = ["stjohns", "saintjohns", "mountpearl", "paradise", "conceptionbay", "cbs", "torbay", "portugalcove", "holyrood", "avalon", "clarenville"];

function findAgent(input: any): any {
  const want = norm(input.community || "");
  if (CENTRAL_NL.some((c) => want.includes(c) || c.includes(want) && want.length > 3)) {
    return {
      note: `${input.community} is in Central Newfoundland — covered by the Turner Realty Team at the Gander office.`,
      site: "https://realestategander.com",
      phone: "709-256-7999",
    };
  }
  if (AVALON.some((c) => want.includes(c) || c.includes(want) && want.length > 3)) {
    return {
      note: `${input.community} is on the Avalon Peninsula — covered by Chris Morrison's team.`,
      site: "https://avalonrealestate.ca",
      phone: "709-725-6520",
    };
  }
  if (want.includes("goosebay") || want.includes("happyvalley") || want.includes("hvgb") || want.includes("northwestriver")) {
    return {
      note: `${input.community} is in the Lake Melville area — covered by The Dynamic Duo at the Goose Bay office.`,
      site: "https://goosebayrealestate.ca",
      phone: "709-896-5001",
    };
  }
  return {
    team: "Royal LePage Turner Realty — Labrador West (no local office)",
    agents: AGENTS,
    office_phone: "709-256-7999",
    note: "Mike Turner, Broker of Record, handles Labrador City and Wabush inquiries. There is no Lab West office address.",
  };
}

// Lab West has one contact (Mike Turner), so a lead is never pinned to an agent here: lead-receive routes it (D-1012-33).
function resolveAgentSlug(_nameGuess: string): string | undefined {
  return undefined;
}

const LEAD_RECEIVE_URL = "https://realestategander.com/.netlify/functions/lead-receive";

async function captureLead(input: any): Promise<any> {
  const diagnostics: any = { saved: false };
  const [first_name, ...rest] = String(input.name || "").trim().split(/\s+/);
  const agentSlug = input.agent_requested ? resolveAgentSlug(input.agent_requested) : undefined;
  // D-1011-05/-06: a recruiting inquiry uses the join-our-team source, so lead-receive's recruiting lane
  // (tools/lead_source_registry.json, audience "recruiting") routes it to Mike, with no consumer auto-reply and no CRM push.
  const recruiting = input.recruiting === true;
  const RECRUIT_SOURCE = "Source: Join Our Team — Agent Recruiting";
  const tags = [
    "chatbot",
    recruiting ? "Recruitment" : null,
    recruiting ? "Agent Recruiting" : null,
    input.community ? `city:${input.community}` : null,
    agentSlug ? `agent:${agentSlug}` : null,
    input.mls ? `mls#${input.mls}` : null,
  ].filter(Boolean) as string[];

  // Route the lead through the real pipeline — same geography/sticky routing,
  // agent email/SMS, and kvCORE push every web-form and phone lead gets.
  // Conv #74: any failure here must never break the chat reply itself.
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    const r = await fetch(LEAD_RECEIVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: SITE },
      signal: controller.signal,
      body: JSON.stringify({
        source: "web",
        source_form_id: recruiting ? RECRUIT_SOURCE : "chatbot",
        lead_source: recruiting ? RECRUIT_SOURCE : "chatbot",
        referer_url: SITE,
        first_name: first_name || undefined,
        last_name: rest.join(" ") || undefined,
        email: input.email,
        phone_number: input.phone || undefined,
        message: recruiting ? `Agent recruiting inquiry (website chat) — ${input.interest}` : input.interest,
        interest_area: input.community || undefined,
        tag: tags,
      }),
    });
    clearTimeout(timeout);
    diagnostics.saved = r.ok;
    if (r.ok) {
      try {
        const body = await r.json();
        if (body && body.agent_routed_to) diagnostics.routed_to = body.agent_routed_to;
      } catch { /* response body optional — ok is the signal that matters */ }
    } else {
      diagnostics.save_error = `lead-receive ${r.status}`;
    }
  } catch (e: any) {
    diagnostics.save_error = `${e?.name}: ${e?.message}`;
  }

  return {
    ok: diagnostics.saved,
    message: diagnostics.saved
      ? (recruiting ? "Recruiting inquiry saved — our broker, Mike Turner, will be in touch." : "Lead captured — Mike Turner will follow up shortly.")
      : "Could not save the lead — give the visitor Mike Turner's number, 709-256-7999, instead.",
    ...diagnostics,
  };
}

async function getListingDetails(input: any): Promise<any> {
  const mls = String(input.mls || "").replace(/[^0-9A-Za-z]/g, "");
  if (!mls) return { error: "no mls" };
  const data = await readActiveBundle();
  if (!data) return { error: "listings feed unavailable (bundle)" };
  const rows: any[] = data.listings || [];
  const row = rows.find((l) => String(l.mls) === mls);
  if (!row) return { error: `MLS ${mls} is not an active listing on this site.` };
  const url = `${SITE}${row.url_path || ""}`;
  // The listing PAGE carries the full Client Full data — fetch + strip to
  // text so the model can answer from it.
  let pageText = "";
  try {
    const pres = await fetch(url, { headers: { "User-Agent": "TurnerAssistant/1.0" } });
    if (pres.ok) {
      pageText = (await pres.text())
        .replace(/<script[\s\S]*?<\/script>/gi, " ")
        .replace(/<style[\s\S]*?<\/style>/gi, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .slice(0, 9000);
    }
  } catch { /* page text optional */ }
  // Strip private_remarks before handing the row to the model.
  const { private_remarks, ...summary } = row;
  return { summary, url, page_text: pageText };
}

async function runTool(name: string, input: any): Promise<any> {
  try {
    if (name === "search_listings") return await searchListings(input);
    if (name === "market_stats") return await marketStats(input);
    if (name === "find_agent") return findAgent(input);
    if (name === "capture_lead") return await captureLead(input);
    if (name === "get_listing_details") return await getListingDetails(input);
    return { error: `unknown tool ${name}` };
  } catch (e: any) {
    return { error: `${e?.name}: ${e?.message}` };
  }
}

// ── Claude call loop ─────────────────────────────────────────────────────
async function anthropic(messages: any[], systemExtra = ""): Promise<any> {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1024,
      output_config: { effort: EFFORT },
      system: systemExtra
        ? [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }, { type: "text", text: systemExtra }]
        : [{ type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } }],
      tools: TOOLS,
      messages,
      // Automatic caching (D-1011-16): the API puts a 5-minute breakpoint on the last message block and moves it
      // forward each turn, so the conversation so far is read from cache on the next call (tool rounds included).
      // It sits alongside the explicit marker on SYSTEM_PROMPT (2 of the 4 breakpoint slots).
      cache_control: { type: "ephemeral" },
    }),
  });
  if (!res.ok) throw new Error(`anthropic ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const json = await res.json();
  // Usage visibility (2026-08-07): the [claude-usage] line below is how caching is checked.
  // Since the move to claude-haiku-5-5 (2026-10-08; minimum cacheable prefix 512 tokens) the SYSTEM_PROMPT marker
  // caches tools + system (~2,700 tokens: cache_write on a conversation's first call, cache_read after). The
  // top-level cache_control above also caches the growing conversation (D-1011-16). Keep everything ahead of
  // the markers byte-stable: TOOLS and SYSTEM_PROMPT are constants, nothing per-request (dates, IDs) goes in
  // them, and systemExtra (the listing page context) follows the marker. cache_read=0 on a repeat call means
  // something upstream changed.
  const u = json.usage || {};
  console.log(`[claude-usage] model=${MODEL} in=${u.input_tokens} out=${u.output_tokens} cache_read=${u.cache_read_input_tokens ?? 0} cache_write=${u.cache_creation_input_tokens ?? 0}`);
  // Haiku 5.5 (D-1008-97): a safety-classifier decline comes back as stop_reason "refusal" (HTTP 200, no
  // fallback model), and a reply can end at max_tokens after a thinking block with no text. Both reach the
  // visitor as the generic "rephrase" line, so log them here where they can be counted.
  if (json.stop_reason === "refusal" || json.stop_reason === "max_tokens") {
    console.warn(`[claude-stop] model=${MODEL} stop_reason=${json.stop_reason} category=${json.stop_details?.category ?? ""}`);
  }
  return json;
}

// Reject-path logging (2026-09-29, Mike's GO): one structured line per refused request so a
// blocked caller is visible in the function log. ONLY status, reason code, the Origin/Referer
// hostname and a timestamp: never an IP, user-agent, header, message or any visitor text.
let limiterDown = false; // set by rateOk when the limiter itself errored (distinguishes limiter_down from rate)
function originHostForLog(event: any): string {
  const h = event.headers || {};
  const raw = String(h["origin"] || h["Origin"] || h["referer"] || h["Referer"] || "");
  if (!raw) return "none";
  try {
    const n = new URL(raw).hostname.toLowerCase();
    return /^[a-z0-9.-]{1,100}$/.test(n) ? n : "invalid";
  } catch {
    return "invalid";
  }
}
function logReject(status: number, reason: string, event: any): void {
  console.log(JSON.stringify({ evt: "chat_reject", status, reason, origin_host: originHostForLog(event), ts: new Date().toISOString() }));
}

// Origin allow-list (2026-09-29): a browser always sends Origin (or at least Referer) on a
// cross-site POST, so a request with neither, or with a foreign one, is a script or another
// site borrowing our Anthropic key. Own domains + this site's Netlify name and deploy previews
// only; fail closed. (CORS headers alone never stop a non-browser caller.)
const ALLOWED_ORIGIN_HOSTS = ["labwestrealty.com", "www.labwestrealty.com", "labwestrealty.netlify.app"];
const PREVIEW_HOST_RE = /^deploy-preview-\d+--labwestrealty\.netlify\.app$/;
function hostOf(v: string): string | null {
  try {
    const u = new URL(v);
    return u.protocol === "https:" ? u.host.toLowerCase() : null;
  } catch {
    return null;
  }
}
function originAllowed(event: any): boolean {
  const h = event.headers || {};
  const raw = String(h["origin"] || h["Origin"] || h["referer"] || h["Referer"] || "");
  if (!raw) return false;
  const host = hostOf(raw);
  return !!host && (ALLOWED_ORIGIN_HOSTS.includes(host) || PREVIEW_HOST_RE.test(host));
}
// Hard size caps (2026-09-29): each message and the whole history are bounded so one request
// cannot carry a huge prompt (input tokens) even inside the 24-turn cap.
const MAX_MSG_CHARS = 4000;
const MAX_HISTORY_CHARS = 30000;

export const handler = async (event: any) => {
  // Dark until generated data exists (see the header). Checked before anything else, for every method and origin.
  if (!(await readActiveBundle())) {
    return { statusCode: 404, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ error: "not_found" }) };
  }
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "https://labwestrealty.com",
    "Access-Control-Allow-Headers": "Content-Type",
  };
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers, body: "" };
  if (event.httpMethod === "GET") return { statusCode: 200, headers, body: JSON.stringify({ ok: true, fn: "chat" }) };
  if (event.httpMethod !== "POST") return { statusCode: 405, headers, body: JSON.stringify({ error: "POST only" }) };
  if (!originAllowed(event)) {
    logReject(403, "origin", event);
    return { statusCode: 403, headers, body: JSON.stringify({ error: "forbidden origin" }) };
  }

  let incoming: any;
  try {
    incoming = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, headers, body: JSON.stringify({ error: "bad json" }) };
  }

  // ── Voice modes (Ship 5 port, 2026-09-12) -- checked BEFORE the ANTHROPIC_API_KEY
  // gate below deliberately: transcription and TTS only need ELEVENLABS_API_KEY,
  // not Claude, so a missing/rotated Anthropic key must never take voice down
  // with it. Both modes hide behind CHAT_VOICE (Conv #74: off -> 404, as if the
  // capability doesn't exist).
  if (incoming.mode === "transcribe" || incoming.mode === "tts") {
    if (CHAT_VOICE_MODE !== "on") {
      return { statusCode: 404, headers, body: JSON.stringify({ ok: false, reason: "not found" }) };
    }
    if (!(await rateOk(`chat_voice_ip_${clientIp(event)}`, 20, 3600, { failClosed: true }))) {
      logReject(429, limiterDown ? "limiter_down" : "rate", event);
      return { statusCode: 429, headers, body: JSON.stringify({ ok: false, reason: "too many requests — try again in a bit" }) };
    }

    if (incoming.mode === "transcribe") {
      const audioB64 = String(incoming.audio_base64 || "");
      const mimeType = String(incoming.mime_type || "audio/webm").slice(0, 60);
      if (!audioB64) return { statusCode: 400, headers, body: JSON.stringify({ ok: false, reason: "no audio" }) };
      let audioBuf: Buffer;
      try {
        audioBuf = Buffer.from(audioB64, "base64");
      } catch {
        return { statusCode: 400, headers, body: JSON.stringify({ ok: false, reason: "bad audio encoding" }) };
      }
      if (!audioBuf.length || audioBuf.length > MAX_TRANSCRIBE_AUDIO_BYTES) {
        return { statusCode: 400, headers, body: JSON.stringify({ ok: false, reason: "audio too large or empty" }) };
      }
      const result = await scribeTranscribe(audioBuf, mimeType);
      if (!result.ok) return { statusCode: 502, headers, body: JSON.stringify({ ok: false, reason: result.reason }) };
      return { statusCode: 200, headers, body: JSON.stringify({ ok: true, text: result.text }) };
    }

    // mode === "tts"
    const text = String(incoming.text || "").trim().slice(0, MAX_TTS_CHARS);
    if (!text) return { statusCode: 400, headers, body: JSON.stringify({ ok: false, reason: "no text" }) };
    if (!(await rateOk("chat_tts_month", CHAT_TTS_MONTHLY_CAP, 2592000, { failClosed: true }))) {
      logReject(429, limiterDown ? "limiter_down" : "rate", event);
      return { statusCode: 429, headers, body: JSON.stringify({ ok: false, reason: "monthly voice budget reached — try again next month" }) };
    }
    const result = await ttsReply(text);
    if (!result.ok) return { statusCode: 502, headers, body: JSON.stringify({ ok: false, reason: result.reason }) };
    return {
      statusCode: 200,
      headers: { ...headers, "Content-Type": "audio/mpeg" },
      body: result.audioB64,
      isBase64Encoded: true,
    };
  }

  if (!ANTHROPIC_API_KEY) {
    return { statusCode: 200, headers, body: JSON.stringify({ error: "unconfigured", fallback: true }) };
  }

  // Rate limit: an unauthenticated LLM proxy (up to ~5 Anthropic calls/request) must
  // not be hammerable. 40 requests / 10 min / IP -- generous for a human, ruinous for
  // a scripted attacker. Fail-CLOSED (2026-09-29): this endpoint spends our Anthropic key, so a
  // limiter outage must stop spend, not remove the guard.
  if (!(await rateOk(`chat:${clientIp(event)}`, 40, 600, { failClosed: true }))) {
    logReject(429, limiterDown ? "limiter_down" : "rate", event);
    return { statusCode: 429, headers, body: JSON.stringify({ error: "rate_limited", retry_after: 600 }) };
  }

  // ── NL search-bar parse mode (2026-06-11): {parse:"query"} → structured
  // filters via a single forced tool call. No conversation, ~1s, ~cheap.
  if (typeof incoming.parse === "string" && incoming.parse.trim()) {
    const q = incoming.parse.trim().slice(0, 300);
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
        body: JSON.stringify({
          model: MODEL,
          max_tokens: 300,
          output_config: { effort: EFFORT },
          system: "Translate real-estate search queries for Newfoundland and Labrador into filters. Prices like '300k' mean 300000. 'under X' → price_max. Cabins → cottage. Only set fields the query implies.",
          tools: [PARSE_TOOL],
          tool_choice: { type: "tool", name: "set_search_filters" },
          messages: [{ role: "user", content: q }],
        }),
      });
      if (!res.ok) throw new Error(`anthropic ${res.status}`);
      const data = await res.json();
      const tu = (data.content || []).find((b: any) => b.type === "tool_use");
      return { statusCode: 200, headers, body: JSON.stringify({ filters: (tu && tu.input) || {} }) };
    } catch (e: any) {
      return { statusCode: 200, headers, body: JSON.stringify({ error: "parse-failed", fallback: true }) };
    }
  }

  let messages: any[] = Array.isArray(incoming.messages) ? incoming.messages : [];
  // History hygiene: cap turns + message size
  messages = messages.slice(-MAX_TURNS).filter(
    (m) => m && (m.role === "user" || m.role === "assistant"),
  );
  // Text only (2026-09-29, FINTRAC/AI-surface audit): the widget only ever sends
  // strings, but this function forwarded whatever content it was handed, so a
  // caller could pass image or document blocks straight to the model on our key.
  // Reject anything that is not a plain string before it can reach the provider.
  if (messages.some((m) => typeof m.content !== "string")) {
    logReject(400, "nontext", event);
    return { statusCode: 400, headers, body: JSON.stringify({ error: "text messages only" }) };
  }
  if (!messages.length || messages[messages.length - 1].role !== "user") {
    return { statusCode: 400, headers, body: JSON.stringify({ error: "last message must be from user" }) };
  }
  const lastText = typeof messages[messages.length - 1].content === "string"
    ? messages[messages.length - 1].content : "";
  if (lastText.length > MAX_MSG_CHARS || messages.some((m) => (m.content as string).length > MAX_MSG_CHARS)) {
    logReject(400, "size", event);
    return { statusCode: 400, headers, body: JSON.stringify({ error: "message too long" }) };
  }
  if (messages.reduce((n, m) => n + (m.content as string).length, 0) > MAX_HISTORY_CHARS) {
    logReject(400, "size", event);
    return { statusCode: 400, headers, body: JSON.stringify({ error: "conversation too long" }) };
  }

  // Listing-page context (Ask-about-this-home): the widget sends the MLS of
  // the page the visitor is on; nudge the model to use the details tool.
  const ctxMls = String(incoming.listing_mls || "").replace(/[^0-9A-Za-z]/g, "").slice(0, 12);
  const ctxStreet = String(incoming.listing_street || "").slice(0, 80);
  const ctxRegion = String(incoming.market_region || "").slice(0, 60);
  const systemExtra = ctxMls
    ? `\n\nCONTEXT: the visitor is currently viewing the listing page for ${ctxStreet || "a property"} (MLS ${ctxMls}). When they ask about "this home/property/house", call get_listing_details with mls=${ctxMls} and answer from it.`
    : ctxRegion
    ? `\n\nCONTEXT: the visitor is on the ${ctxRegion} market-statistics page. When they ask about "this market/area/town" or prices/trends, call market_stats scoped to ${ctxRegion} and answer from it.`
    : "";

  try {
    let response = await anthropic(messages, systemExtra);
    let toolRounds = 0;
    // Tool-use loop (max 4 rounds per turn)
    while (response.stop_reason === "tool_use" && toolRounds < 4) {
      toolRounds += 1;
      const toolResults: any[] = [];
      for (const block of response.content) {
        if (block.type === "tool_use") {
          const result = await runTool(block.name, block.input || {});
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: JSON.stringify(result).slice(0, 12000),
          });
        }
      }
      messages = [...messages, { role: "assistant", content: response.content }, { role: "user", content: toolResults }];
      response = await anthropic(messages, systemExtra);
    }
    const text = (response.content || [])
      .filter((b: any) => b.type === "text")
      .map((b: any) => b.text)
      .join("\n")
      .trim();
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ reply: text || "Sorry — I had trouble with that one. Could you rephrase?", tool_rounds: toolRounds }),
    };
  } catch (e: any) {
    console.error("chat error:", e?.message);
    return { statusCode: 200, headers, body: JSON.stringify({ error: "upstream", fallback: true }) };
  }
};
