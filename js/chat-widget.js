/* chat-widget.js — "Turner Assistant" AI chat widget (Lab West port, sites D-1012-34).
 *
 * Convention #15 port from Gander. Goosebay never had Tawk. Self-
 * contained: injects its own styles + DOM, talks to /api/chat (Netlify fn
 * running Claude with server-side tools over Turner's live listing data).
 *
 * Conv #74 fail-safes: API error/unconfigured → inline "leave a message" lead
 * mini-form (posts back through the same function's capture flow via a plain
 * message). Conversation history lives in sessionStorage (per-tab), capped.
 */
(function tcBoot() {
  "use strict";
  // Loaded async in <head> on some pages, so it can run before <body>
  // exists; wait for the DOM instead of throwing on document.body (2026-10-09).
  if (!document.body) { document.addEventListener("DOMContentLoaded", tcBoot); return; }
  if (window.__turnerChatLoaded) return;
  window.__turnerChatLoaded = true;

  var API = "/api/chat";
  var STORE_KEY = "turner-chat-v1";
  var MAX_CLIENT_TURNS = 20;

  // ── Keyboard watch (shared snippet, fleet 2026-10-06) ───────────────────
  // Same block is carried by js/app-shell.js, js/mobile-action-bar.js and
  // js/chat-widget.js; whichever runs first installs it (window.__tnrKbWatch).
  // Sets html.tnr-kb-open while a phone keyboard is up: the visual viewport is
  // much shorter than the layout viewport, OR (touch devices) a text field has
  // focus. CSS keyed on that class hides the sticky Call/Text/Book bar, the
  // chat launcher, the "Get the app" card and the Registry pill; the chat
  // panel sizes itself to the visual viewport. Fires "tnr:keyboard".
  (function () {
    if (window.__tnrKbWatch) return;
    window.__tnrKbWatch = true;
    var root = document.documentElement, vv = window.visualViewport;
    var on = false, focused = false, timer = null, touch = false;
    try { touch = (navigator.maxTouchPoints || 0) > 0 || (window.matchMedia && window.matchMedia("(pointer:coarse)").matches); } catch (e) {}
    function isField(el) {
      if (!el || el.nodeType !== 1) return false;
      if (el.tagName === "TEXTAREA") return !el.readOnly;
      if (el.tagName === "INPUT") return !/^(button|checkbox|radio|submit|reset|file|image|range|color|hidden|date|time|datetime-local|month|week)$/i.test(el.type || "text");
      return !!el.isContentEditable;
    }
    function update() {
      var shrunk = !!vv && vv.scale <= 1.02 && (window.innerHeight - vv.height) > 150;
      var now = shrunk || (touch && focused);
      if (now === on) return;
      on = now;
      root.classList.toggle("tnr-kb-open", on);
      try { window.dispatchEvent(new CustomEvent("tnr:keyboard", { detail: { open: on } })); } catch (e) {}
    }
    document.addEventListener("focusin", function (e) { focused = isField(e.target); update(); });
    document.addEventListener("focusout", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { focused = isField(document.activeElement); update(); }, 80);
    });
    if (vv) vv.addEventListener("resize", update);
  })();

  // ── styles ──
  var css = [
    "#tc-bubble{position:fixed;right:18px;bottom:18px;z-index:9500;width:58px;height:58px;border-radius:50%;background:#EA002A;color:#fff;border:0;cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;transition:transform .15s}",
    "#tc-bubble:hover{transform:scale(1.06)}",
    "html.tnr-kb-open #tc-bubble{display:none}",
    // FORM_CLEAR (redesign 2026-10-09, D-1009-77 item 5): js/mobile-action-bar.js sets html.tnr-form-clear (switch on, phone) while a form is in view or has focus; the launcher steps aside unless its panel is open
    "html.tnr-form-clear:not(.tc-chat-open) #tc-bubble{display:none}",
    "#tc-bubble.tc-clear{opacity:0 !important;pointer-events:none !important}",
    "#tc-bubble svg{width:28px;height:28px;fill:#fff}",
    "#tc-panel{position:fixed;right:18px;bottom:88px;z-index:9500;width:360px;max-width:calc(100vw - 24px);height:520px;max-height:calc(100vh - 120px);background:#16161a;border:1px solid #2c2c33;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.5);display:none;flex-direction:column;overflow:hidden;font-family:Roboto,system-ui,-apple-system,sans-serif}",
    "#tc-panel.tc-open{display:flex}",
    "#tc-head{background:#EA002A;color:#fff;padding:13px 16px;display:flex;align-items:center;gap:10px}",
    "#tc-head .tc-title{font-weight:700;font-size:15px;line-height:1.2}",
    "#tc-head .tc-sub{font-size:11px;opacity:.85}",
    "#tc-close{margin-left:auto;background:none;border:0;color:#fff;font-size:20px;cursor:pointer;padding:2px 6px}",
    "#tc-log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}",
    ".tc-msg{max-width:85%;padding:9px 13px;border-radius:12px;font-size:13.5px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}",
    ".tc-msg a{color:#ff4d6d;text-decoration:underline}",
    ".tc-user{align-self:flex-end;background:#EA002A;color:#fff;border-bottom-right-radius:4px}",
    ".tc-bot{align-self:flex-start;background:#26262c;color:#e8e8ec;border-bottom-left-radius:4px}",
    ".tc-typing{align-self:flex-start;color:#9a9aa2;font-size:12px;padding:4px 13px}",
    "#tc-form{display:flex;gap:8px;padding:12px;border-top:1px solid #2c2c33;background:#1b1b20}",
    "#tc-input{flex:1;background:#26262c;border:1px solid #34343c;border-radius:9px;color:#fff;padding:10px 12px;font-size:13.5px;font-family:inherit;outline:none}",
    "#tc-input:focus{border-color:#EA002A}",
    "#tc-send{background:#EA002A;border:0;border-radius:9px;color:#fff;padding:0 16px;font-weight:700;cursor:pointer;font-size:13.5px}",
    "#tc-send:disabled{opacity:.5;cursor:default}",
    "#tc-foot{font-size:10px;color:#77777e;text-align:center;padding:0 12px 9px;background:#1b1b20}",
    "#tc-voice-toggle{background:none;border:0;color:#fff;cursor:pointer;padding:2px 6px;opacity:.75;border-radius:6px}",
    "#tc-voice-toggle[aria-pressed=\"true\"]{opacity:1;background:rgba(255,255,255,.18)}",
    "#tc-voice-toggle svg{width:17px;height:17px;display:block}",
    "#tc-mic{background:#26262c;border:1px solid #34343c;border-radius:9px;color:#e8e8ec;width:40px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}",
    "#tc-mic[aria-pressed=\"true\"]{background:#EA002A;border-color:#EA002A;color:#fff;animation:tc-rec-pulse 1.1s ease-in-out infinite}",
    "#tc-mic svg{width:17px;height:17px}",
    "@keyframes tc-rec-pulse{0%,100%{opacity:1}50%{opacity:.55}}",
    "#tc-voice-status{font-size:11px;color:#9a9aa2;text-align:center;padding:0 12px 6px;background:#1b1b20}",
    "@media (max-width:480px){#tc-panel{right:8px;bottom:80px;width:calc(100vw - 16px);height:65vh}}",
  ].join("\n");
  var styleEl = document.createElement("style");
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // ── DOM ──
  var bubble = document.createElement("button");
  bubble.id = "tc-bubble";
  bubble.setAttribute("aria-label", "Chat with Turner Assistant");
  bubble.innerHTML =
    '<svg viewBox="0 0 24 24"><path d="M12 3C6.5 3 2 6.9 2 11.7c0 2.6 1.3 4.9 3.4 6.5-.1.8-.5 2.1-1.5 3.3 0 0 2.4-.3 4.3-1.6 1.2.4 2.5.6 3.8.6 5.5 0 10-3.9 10-8.8S17.5 3 12 3z"/></svg>';
  var panel = document.createElement("div");
  panel.id = "tc-panel";
  panel.innerHTML =
    '<div id="tc-head"><div><div class="tc-title">Turner Assistant</div><div class="tc-sub">AI assistant · Royal LePage Turner Realty</div></div>' +
    '<button id="tc-voice-toggle" type="button" aria-pressed="false" aria-label="Turn on spoken replies" hidden>' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>' +
    '</button>' +
    '<button id="tc-close" aria-label="Close chat">×</button></div>' +
    '<div id="tc-log"></div>' +
    '<div id="tc-voice-status" hidden></div>' +
    '<form id="tc-form"><input id="tc-input" type="text" autocomplete="off" placeholder="Ask about listings, prices, towns…" maxlength="1000">' +
    '<button id="tc-mic" type="button" aria-pressed="false" aria-label="Ask by voice" hidden>' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>' +
    '</button>' +
    '<button id="tc-send" type="submit">Send</button></form>' +
    '<div id="tc-foot">AI assistant — answers come from live Turner Realty data. Royal LePage Turner Realty · Mike Turner, Broker of Record · 709-256-7999</div>';
  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  // First-paint declutter (CX cycle 2026-07-14): on phones the launcher sat on
  // top of in-flow hero CTAs at first paint (seen overlapping the homepage
  // "Free Home Evaluation" button at 375px). Start hidden on small viewports;
  // reveal on first scroll or after 4s — whichever comes first. Desktop unchanged.
  if (window.innerWidth <= 480) {
    bubble.style.opacity = "0";
    bubble.style.pointerEvents = "none";
    bubble.style.transition = "opacity .3s";
    var _revealed = false;
    var _revealBubble = function () {
      if (_revealed) return; _revealed = true;
      bubble.style.opacity = "1"; bubble.style.pointerEvents = "";
      window.removeEventListener("scroll", _revealBubble);
    };
    window.addEventListener("scroll", _revealBubble, { passive: true });
    // No timer fallback: while the user sits on the hero they already face
    // CALL NOW / FIND A HOME / FREE EVALUATION — a timed reveal just re-creates
    // the overlap for slow readers. Chat's discovery moment is after scroll.
  }

  // Keep the launcher + panel clear of the mobile bottom action bar
  // (Call/Text/…). It's fixed at bottom:0 with a higher z-index and is
  // JS-injected (js/mobile-action-bar.js's .mab-bar, 2026-09-17 —
  // replaced the older .rf-sticky-bar / listing-page .lst-mobile-cta,
  // kept in this selector list as a harmless no-op fallback in case
  // either is still present on an unregenerated page), some toggling on
  // scroll — so re-measure on load, resize, scroll, and shortly after
  // mount. Mike 2026-06-13: the bubble was hidden behind the bottom bar
  // on mobile. When no bar is present the launcher returns to its 18px
  // resting spot.
  var _rafPending = false;
  function positionWidget() {
    _rafPending = false;
    var bar = document.querySelector(".mab-bar, .rf-sticky-bar, .lst-mobile-cta");
    var h = (bar && getComputedStyle(bar).display !== "none") ? bar.offsetHeight : 0;
    var b = h > 0 ? (h + 18) : 18;  // D-1009-69: 18px clear of the Call/Text/Book bar (was 14)
    // Fleet slice 3 (2026-10-06): the "Get the app" card (js/app-shell.js,
    // z-index 9550) used to cover the launcher. When the card is showing, lift
    // the launcher above it. While the chat panel is open the card is hidden
    // (css/app-shell.css, html.tc-chat-open), so the launcher drops back.
    var card = document.getElementById("tnr-install-cta");
    if (card && !document.documentElement.classList.contains("tc-chat-open") && getComputedStyle(card).display !== "none") {
      var cr = card.getBoundingClientRect();
      if (cr.height > 0) b = Math.max(b, Math.round(window.innerHeight - cr.top + 10));
    }
    bubble.style.bottom = b + "px";
    if (!panel.style.top) panel.style.bottom = (b + 70) + "px";  // 58px bubble + 12px gap
    avoidBadges();
  }

  // D-1009-69 (outside review of the live Avalon homepage): the launcher crowded the hero's trust badges (.hx-proof chips). While any badge
  // sits under the launcher's box, the launcher steps aside (class tc-clear: transparent, not clickable) and comes back the moment the
  // badges scroll clear. Never while the chat panel is open. A page with no .hx-proof is untouched.
  function avoidBadges() {
    var chips = document.querySelectorAll(".hx-proof span");
    var hit = false;
    if (chips.length && !panel.classList.contains("tc-open")) {
      var a = bubble.getBoundingClientRect();
      for (var i = 0; i < chips.length && !hit; i++) {
        var c = chips[i].getBoundingClientRect();
        hit = c.width > 0 && Math.min(a.right, c.right) - Math.max(a.left, c.left) > 0 && Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top) > 0;
      }
    }
    bubble.classList.toggle("tc-clear", hit);
  }
  function _schedulePosition() {
    if (!_rafPending) { _rafPending = true; requestAnimationFrame(positionWidget); }
  }
  positionWidget();
  window.addEventListener("resize", _schedulePosition, { passive: true });
  window.addEventListener("scroll", _schedulePosition, { passive: true });
  window.addEventListener("tnr:floating", _schedulePosition);  // app card shown / hidden
  setTimeout(positionWidget, 1000);  // sticky bars mount async

  // Keyboard (fleet slice 3): while the phone keyboard is up and the panel is
  // open, size the panel to the VISUAL viewport so the input stays on screen
  // (the layout viewport does not shrink for the keyboard on iOS).
  function fitPanelToViewport() {
    var vv = window.visualViewport;
    var kb = document.documentElement.classList.contains("tnr-kb-open");
    if (panel.classList.contains("tc-open") && kb && vv) {
      panel.style.top = Math.round(vv.offsetTop + 8) + "px";
      panel.style.bottom = "auto";
      panel.style.height = Math.max(200, Math.round(vv.height - 16)) + "px";
      panel.style.maxHeight = "none";
    } else if (panel.style.top) {
      panel.style.top = ""; panel.style.height = ""; panel.style.maxHeight = "";
      positionWidget();
    }
  }
  window.addEventListener("tnr:keyboard", fitPanelToViewport);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", fitPanelToViewport);
    window.visualViewport.addEventListener("scroll", fitPanelToViewport);
  }

  var log = panel.querySelector("#tc-log");
  var form = panel.querySelector("#tc-form");
  var input = panel.querySelector("#tc-input");
  var send = panel.querySelector("#tc-send");
  var micBtn = panel.querySelector("#tc-mic");
  var voiceToggle = panel.querySelector("#tc-voice-toggle");
  var voiceStatus = panel.querySelector("#tc-voice-status");

  // ── history (per-tab) ──
  var history = [];
  try {
    history = JSON.parse(sessionStorage.getItem(STORE_KEY) || "[]");
  } catch (e) { history = []; }

  function persist() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(history.slice(-MAX_CLIENT_TURNS))); } catch (e) {}
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function linkify(s) {
    return esc(s).replace(/(https?:\/\/[^\s)]+)/g, function (u) {
      return '<a href="' + u + '" target="_blank" rel="noopener">' + u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 48) + "</a>";
    });
  }

  function addMsg(role, text) {
    var div = document.createElement("div");
    div.className = "tc-msg " + (role === "user" ? "tc-user" : "tc-bot");
    div.innerHTML = linkify(text);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function showTyping(on) {
    var t = log.querySelector(".tc-typing");
    if (on && !t) {
      t = document.createElement("div");
      t.className = "tc-typing";
      t.textContent = "Turner Assistant is typing…";
      log.appendChild(t);
      log.scrollTop = log.scrollHeight;
    } else if (!on && t) t.remove();
  }

  // Listing-page context (Ask-about-this-home, 2026-06-11): generator emits
  // window.__tcListing = {mls, street} on listing-detail pages.
  var LISTING = (window.__tcListing && window.__tcListing.mls) ? window.__tcListing : null;
  // Market-stats page context (2026-06-12): "ask about this market"
  var MARKET = (window.__tcMarket && window.__tcMarket.region) ? window.__tcMarket : null;

  var GREETING = LISTING
    ? "Hi! I'm Turner Assistant 👋 Ask me anything about " + LISTING.street + " — taxes, heating, lot size, schools — or about the local market."
    : (MARKET
      ? "Hi! I'm Turner Assistant 👋 Ask me anything about the " + MARKET.region + " market — prices, days on market, what's selling — or about specific listings."
      : "Hi! I'm Turner Assistant 👋 I can search our live Labrador West listings, share market stats, or connect you with Mike Turner, Broker of Record. What can I help with?");

  function renderHistory() {
    log.innerHTML = "";
    if (!history.length) addMsg("assistant", GREETING);
    history.forEach(function (m) { addMsg(m.role, m.content); });
  }

  var open = false;
  function toggle(want) {
    open = typeof want === "boolean" ? want : !open;
    panel.classList.toggle("tc-open", open);
    document.documentElement.classList.toggle("tc-chat-open", open);  // css/app-shell.css hides the app card
    if (open) { renderHistory(); input.focus(); }
    positionWidget();
    fitPanelToViewport();
  }
  bubble.addEventListener("click", function () { toggle(); });
  window.__tcOpenChat = function () { toggle(true); };
  panel.querySelector("#tc-close").addEventListener("click", function () { toggle(false); });

  // ── Voice (Ship 5 port, 2026-09-12 -- Gander canary 2026-09-10,
  // ~/.claude/plans/now-that-we-have-polymorphic-wolf.md) ──
  // Progressive enhancement: the mic + speaker controls only appear when the
  // browser actually supports MediaRecorder/getUserMedia. Whether the SERVER
  // gate (CHAT_VOICE) is on is unknown until the first real request -- a 404
  // from either endpoint means "off" and permanently hides both controls for
  // the rest of this session (Conv #74: never leave a dead button visible).
  var voiceRepliesOn = false;
  var recording = false;
  var mediaRecorder = null;
  var recordedChunks = [];
  var recordTimer = null;
  var voiceGateKnownOff = false;
  var MAX_RECORD_MS = 20000;

  function voiceSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function pickMimeType() {
    var candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    for (var i = 0; i < candidates.length; i++) {
      if (window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(candidates[i])) return candidates[i];
    }
    return "";
  }

  function setVoiceStatus(text) {
    if (!voiceStatus) return;
    if (text) { voiceStatus.textContent = text; voiceStatus.hidden = false; }
    else voiceStatus.hidden = true;
  }

  function hideVoiceControls() {
    micBtn.hidden = true;
    voiceToggle.hidden = true;
    setVoiceStatus("");
  }

  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onloadend = function () {
        var result = reader.result || "";
        var idx2 = result.indexOf(",");
        resolve(idx2 >= 0 ? result.slice(idx2 + 1) : result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
    if (recordTimer) { clearTimeout(recordTimer); recordTimer = null; }
  }

  function transcribeAndSend(blob, mimeType) {
    setVoiceStatus("Transcribing…");
    blobToBase64(blob).then(function (b64) {
      return fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "transcribe", audio_base64: b64, mime_type: mimeType }),
      });
    }).then(function (r) {
      if (r.status === 404) { voiceGateKnownOff = true; hideVoiceControls(); throw new Error("gate off"); }
      return r.json();
    }).then(function (j) {
      setVoiceStatus("");
      if (j && j.ok && j.text) {
        input.value = j.text;
        if (form.requestSubmit) form.requestSubmit();
        else form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
      } else {
        setVoiceStatus((j && j.reason) || "Couldn't hear that clearly — try again.");
        setTimeout(function () { setVoiceStatus(""); }, 3000);
      }
    }).catch(function () {
      setVoiceStatus("");
    });
  }

  function startRecording() {
    if (voiceGateKnownOff || recording) return;
    var mimeType = pickMimeType();
    if (!mimeType) { setVoiceStatus("Voice input isn't supported in this browser."); setTimeout(function () { setVoiceStatus(""); }, 3000); return; }
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(function (stream) {
        recording = true;
        micBtn.setAttribute("aria-pressed", "true");
        setVoiceStatus("Listening… tap the mic to stop");
        recordedChunks = [];
        mediaRecorder = new MediaRecorder(stream, { mimeType: mimeType });
        mediaRecorder.addEventListener("dataavailable", function (e) {
          if (e.data && e.data.size) recordedChunks.push(e.data);
        });
        mediaRecorder.addEventListener("stop", function () {
          recording = false;
          micBtn.setAttribute("aria-pressed", "false");
          stream.getTracks().forEach(function (t) { t.stop(); });
          if (!recordedChunks.length) { setVoiceStatus(""); return; }
          var blob = new Blob(recordedChunks, { type: mimeType });
          transcribeAndSend(blob, mimeType.split(";")[0]);
        });
        mediaRecorder.start();
        recordTimer = setTimeout(stopRecording, MAX_RECORD_MS);
      })
      .catch(function () {
        setVoiceStatus("Couldn't access your microphone — check your browser's site permissions.");
        setTimeout(function () { setVoiceStatus(""); }, 4000);
      });
  }

  function playReply(text) {
    fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "tts", text: text }),
    }).then(function (r) {
      if (r.status === 404) { voiceGateKnownOff = true; hideVoiceControls(); throw new Error("gate off"); }
      if (!r.ok) throw new Error("tts failed");
      return r.blob();
    }).then(function (blob) {
      var audio = new Audio(URL.createObjectURL(blob));
      audio.play().catch(function () {});
    }).catch(function () {});
  }

  if (voiceSupported()) {
    micBtn.hidden = false;
    voiceToggle.hidden = false;
    micBtn.addEventListener("click", function () {
      if (recording) stopRecording(); else startRecording();
    });
    voiceToggle.addEventListener("click", function () {
      voiceRepliesOn = !voiceRepliesOn;
      voiceToggle.setAttribute("aria-pressed", voiceRepliesOn ? "true" : "false");
      voiceToggle.setAttribute("aria-label", voiceRepliesOn ? "Turn off spoken replies" : "Turn on spoken replies");
    });
  }

  var FALLBACK =
    "I'm having trouble connecting right now. You can reach Mike Turner directly at 709-256-7999 or miketurner@royallepage.ca — or just leave your name, email, and what you're looking for here and I'll pass it along as soon as I'm back.";

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || send.disabled) return;
    input.value = "";
    addMsg("user", text);
    history.push({ role: "user", content: text });
    persist();
    send.disabled = true;
    showTyping(true);
    fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(LISTING
        ? { messages: history.slice(-MAX_CLIENT_TURNS), listing_mls: LISTING.mls, listing_street: LISTING.street }
        : (MARKET
          ? { messages: history.slice(-MAX_CLIENT_TURNS), market_region: MARKET.region }
          : { messages: history.slice(-MAX_CLIENT_TURNS) })),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        showTyping(false);
        send.disabled = false;
        var reply = j && j.reply ? j.reply : FALLBACK;
        addMsg("assistant", reply);
        history.push({ role: "assistant", content: reply });
        persist();
        input.focus();
        if (voiceRepliesOn) playReply(reply);
      })
      .catch(function () {
        showTyping(false);
        send.disabled = false;
        addMsg("assistant", FALLBACK);
        history.push({ role: "assistant", content: FALLBACK });
        persist();
      });
  });
})();
