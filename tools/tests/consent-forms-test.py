#!/usr/bin/env python3
"""consent-forms-test.py -- STRICT 2246 (sites, 2026-10-27, D-1027-02 + the forms parts of D-1027-03).

Mike pasted a CASL review (D-1027-02) and a mobile test (D-1027-03). This guards what came out of them, on whichever of the five
sites it runs in (byte-identical in all five repos; a check that has nothing to look at on a site says so and passes):

  static   js/consent-forms.js exists and boldtrail-forms.js loads it with the file's current hash; the Listing Email Alerts
           form is written with a REQUIRED express-consent checkbox naming "Listing Email Alerts", the brokerage address and the
           unsubscribe line; the shared form CSS is 16px; the privacy policy has a "How to Unsubscribe" section; the contact
           form's name / email / phone fields carry autocomplete tokens.
  browser  (Playwright + Chromium, served from this checkout, every external host blocked, nothing really sent)
           - the contact page, the home-value / landing-page forms and one listing page's Book a Showing form each show the
             one-line notice under Submit and an OPTIONAL, UNTICKED "Also email me updates" box whose whole row is >= 44 px tall;
           - no visible text input / select / textarea on those pages is under 16 px;
           - the Listing Email Alerts form cannot be submitted with its box unticked (checkValidity false);
           - a submitted contact form posts marketing_optin false + consent_type implied (box unticked) and true + express (ticked),
             each with consent_at and consent_page, and the Alerts form posts express.
           A form this test finds with an email or phone field, outside the skip list, and no notice is a failure.

Exit 0 pass, 1 fail, 2 cannot run (fails closed). CONSENT_BROWSER=0 skips the browser half locally; CI never sets it.
Not legal advice: the wording is for a lawyer to confirm.
"""
import functools
import glob
import hashlib
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYWRIGHT_VERSION = "1.60.0"
FAILS = []
NOTES = []


def log(m):
    print(m, flush=True)


def check(ok, name, detail=""):
    if ok:
        log("[PASS] " + name)
    else:
        FAILS.append(name)
        log("[FAIL] " + name + (" -- " + str(detail)[:300] if detail else ""))


def first(*cands):
    for c in cands:
        if (ROOT / c).is_file():
            return c
    return None


# ----------------------------------------------------------------------------------------------------------- static half
def static_checks():
    cf = ROOT / "js" / "consent-forms.js"
    bt = ROOT / "js" / "boldtrail-forms.js"
    forms_site = bt.is_file() or cf.is_file()
    if not forms_site:
        NOTES.append("this site has no lead forms (no boldtrail-forms.js, no consent-forms.js): privacy-policy checks only")
    else:
        check(cf.is_file(), "S1 js/consent-forms.js exists", "missing")
    if cf.is_file():
        src = cf.read_text(encoding="utf-8")
        for needle in ("Also email me updates", "By sending, you agree we may contact you about this request.",
                       "Unsubscribe any time from the link in every email.", "Royal LePage Turner Realty, 204 Airport Blvd, Gander NL A1V 1L6",
                       "consent_at", "consent_type", "marketing_optin"):
            check(needle in src, "S2 consent-forms.js carries: " + needle)
    if bt.is_file():
        s = bt.read_text(encoding="utf-8")
        h8 = hashlib.sha256(cf.read_bytes()).hexdigest()[:8] if cf.is_file() else "?"
        check(("consent-forms.js') + '?v=" + h8) in s,
              "S3 boldtrail-forms.js loads consent-forms.js with the file's current hash (" + h8 + ")")
        a = s.find("function listingAlerts(")
        b = s.find("// ═", a)
        fn = s[a:b]
        check('data-consent="alerts"' in fn, "S4 Listing Email Alerts form is marked data-consent=alerts")
        m = re.search(r'<input[^>]*data-tc="alerts"[^>]*>', fn)
        check(bool(m) and " required" in m.group(0) and 'type="checkbox"' in m.group(0), "S5 its consent checkbox is a required checkbox")
        for needle in ("Listing Email Alerts", "Royal LePage Turner Realty, 204 Airport Blvd, Gander NL A1V 1L6",
                       "Unsubscribe any time from the link in every email."):
            check(needle in fn, "S6 its consent wording carries: " + needle)
        check("name=\"marketing_optin\"" in fn, "S7 its checkbox is the marketing_optin field lead-receive records")
        m = re.search(r"\.rf-form-wrap input, \.rf-form-wrap select, \.rf-form-wrap textarea \{[^}]*font-size: ([^;]+);", s)
        check(bool(m) and m.group(1).strip() == "16px", "S8 shared form CSS inputs are 16px", m.group(1) if m else "rule not found")
    else:
        NOTES.append("no js/boldtrail-forms.js on this site: loader / Alerts checks not applicable")
    pp = first("pages/privacy-policy.html", "privacy-policy.html")
    check(pp is not None, "S9 privacy policy page exists")
    if pp:
        t = (ROOT / pp).read_text(encoding="utf-8")
        check(re.search(r"<h[23][^>]*>\s*(?:[\d.]+\s*)?(How to Unsubscribe|Withdrawal of Consent)\s*</h[23]>", t) is not None, "S10 privacy policy has a \"How to Unsubscribe\" / withdrawal-of-consent section")
        check('clicking "unsubscribe" in our emails' in t, "S11 it carries the Goose Bay unsubscribe wording")
    contact = first("pages/contact.html", "contact.html")
    if contact and forms_site:
        t = (ROOT / contact).read_text(encoding="utf-8")
        for field, tokens in (("email", ("email",)), ("phone", ("tel",))):
            m = re.search(r'<input[^>]*id="%s"[^>]*>' % field, t)
            check(bool(m) and any(('autocomplete="%s"' % k) in m.group(0) for k in tokens), "S12 contact %s field has autocomplete" % field,
                  m.group(0) if m else "not found")
    else:
        NOTES.append("no contact page on this site")


# ----------------------------------------------------------------------------------------------------------- browser half
def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return sync_playwright
    except ImportError:
        pass
    base = os.environ.get("LISTINGS_SMOKE_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "turner-listings-smoke")
    target = os.path.join(base, "py%d%d-playwright-%s" % (sys.version_info[0], sys.version_info[1], PLAYWRIGHT_VERSION))
    if not os.path.isdir(os.path.join(target, "playwright")):
        log("[consent] installing playwright==%s into %s" % (PLAYWRIGHT_VERSION, target))
        os.makedirs(base, exist_ok=True)
        tmp = target + ".tmp%d" % os.getpid()
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--target", tmp,
                            "playwright==" + PLAYWRIGHT_VERSION])
        if r.returncode != 0:
            raise RuntimeError("pip install playwright failed")
        try:
            os.rename(tmp, target)
        except OSError:
            pass
    sys.path.insert(0, target)
    os.environ["PYTHONPATH"] = target + os.pathsep + os.environ.get("PYTHONPATH", "")
    from playwright.sync_api import sync_playwright
    return sync_playwright


def ensure_browser():
    cmd = [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"]
    if os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted":
        cmd.insert(4, "--with-deps")
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        log(r.stdout[-1500:])
        raise RuntimeError("playwright install chromium failed")


class _H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve():
    httpd = _S(("127.0.0.1", 0), functools.partial(_H, directory=str(ROOT)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


PAGE_SCAN = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const out = {forms: [], small: []};
  document.querySelectorAll('input,select,textarea').forEach(e => {
    if (['hidden','checkbox','radio','submit','button','image','file','range','color'].includes(e.type)) return;
    if (!vis(e)) return;
    const fs = parseFloat(getComputedStyle(e).fontSize);
    if (fs < 15.99) out.small.push((e.name || e.id || e.type) + '=' + fs);
  });
  document.querySelectorAll('form').forEach(f => {
    const lead = !!f.querySelector('input[type=email],input[type=tel],input[name=email],input[name=phone]');
    if (!lead) return;
    const tc = window.TurnerConsent;
    const opt = f.querySelector('input[name=marketing_optin]');
    const row = opt ? (opt.closest('label') || opt.parentElement) : null;
    out.forms.push({
      own: !!f.querySelector('input[type=checkbox][id*=consent],input[type=checkbox][name*=consent],input[type=checkbox][class*=consent],input[name=agent_consent]'),
      id: f.id || f.className || '(form)', hasLine: !!f.querySelector('[data-consent-line]'),
      done: !!f.getAttribute('data-consent-done'), kind: f.getAttribute('data-consent-kind') || f.getAttribute('data-consent') || '',
      hasOpt: !!opt, optChecked: opt ? opt.checked : null, optRequired: opt ? opt.required : null,
      rowH: row ? row.getBoundingClientRect().height : 0, visible: vis(f)
    });
  });
  return out;
}"""


def browser_checks():
    if not (ROOT / "js" / "consent-forms.js").is_file():
        NOTES.append("no consent-forms.js on this site: browser half not applicable")
        return
    if os.environ.get("CONSENT_BROWSER") == "0":
        NOTES.append("browser half skipped (CONSENT_BROWSER=0)")
        return
    sync_playwright = ensure_playwright()
    ensure_browser()
    httpd, base = serve()
    pages = []
    for c in ("pages/contact.html", "contact.html", "pages/home-value.html", "pages/lp-buy.html", "pages/lp-sell.html"):
        if (ROOT / c).is_file():
            pages.append(c)
    listing = None
    for f in sorted(glob.glob(str(ROOT / "listings" / "*" / "*.html")))[:3000]:
        try:
            if "BoldTrailForms.bookShowing" in Path(f).read_text(encoding="utf-8", errors="replace"):
                listing = os.path.relpath(f, ROOT)
                break
        except OSError:
            pass
    if listing:
        pages.append(listing)
    else:
        NOTES.append("no listing page with a Book a Showing form on this site")
    if not pages:
        NOTES.append("no form pages on this site: browser half has nothing to open")
        return
    posts = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)

        def route(rt):
            u = rt.request.url
            if "lead-receive" in u:
                if rt.request.method == "POST":
                    try:
                        posts.append(json.loads(rt.request.post_data or "{}"))
                    except ValueError:
                        posts.append({"_raw": rt.request.post_data})
                    return rt.fulfill(status=200, content_type="application/json", body='{"ok":true}',
                                      headers={"access-control-allow-origin": "*"})
                return rt.fulfill(status=204, headers={"access-control-allow-origin": "*"})
            if u.startswith(base):
                return rt.continue_()
            return rt.abort()

        ctx.route("**/*", route)
        for rel in pages:
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/" + rel, wait_until="load")
            pg.wait_for_timeout(2500)
            r = pg.evaluate(PAGE_SCAN)
            leads = [f for f in r["forms"] if f["visible"] or f["done"] or f["hasLine"]]
            if not leads:
                NOTES.append("%s: no lead form rendered at load (it may appear after a step)" % rel)
            for f in leads:
                ok = f["hasLine"] or f["kind"] == "alerts" or f["own"]   # a form with its own consent box (Listing Text Alerts, sign-ups) is not given a second one
                check(ok, "B2 %s: form '%s' shows the consent line" % (rel, f["id"]), f)
                if f["kind"] == "inquiry":
                    check(f["hasOpt"] and f["optChecked"] is False and not f["optRequired"],
                          "B3 %s: form '%s' has an optional UNTICKED email box" % (rel, f["id"]), f)
                    if f["visible"]:
                        check(f["rowH"] >= 43.5, "B4 %s: its box row is >= 44 px tall" % rel, f["rowH"])
            check(not r["small"], "B5 %s: no visible input / select / textarea under 16 px" % rel, r["small"][:6])
            check(not [e for e in errs if "consent" in e.lower()], "B6 %s: no consent-forms script error" % rel, errs[:2])
            pg.close()

        # the Listing Email Alerts form, rendered by the form library into a scratch container
        probe = None
        for cand in ("pages/contact.html", "contact.html", "index.html"):
            if (ROOT / cand).is_file() and "boldtrail-forms.js" in (ROOT / cand).read_text(encoding="utf-8", errors="replace"):
                probe = cand
                break
        if probe is None:
            NOTES.append("no probe page loads boldtrail-forms.js: Alerts and dynamic-form checks skipped")
        if not (ROOT / "js" / "boldtrail-forms.js").is_file():
            NOTES.append("no boldtrail-forms.js: Listing Email Alerts form checks not applicable")
        if (ROOT / "js" / "boldtrail-forms.js").is_file() and probe:
            pg = ctx.new_page()
            pg.goto(base + "/" + probe, wait_until="load")
            pg.wait_for_timeout(1500)
            pg.evaluate("() => { const d = document.createElement('div'); d.id = 'alerts-probe'; document.body.appendChild(d); BoldTrailForms.listingAlerts('#alerts-probe'); }")
            pg.wait_for_timeout(800)
            a = pg.evaluate("""() => { const f = document.querySelector('#alerts-probe form'); const c = f.querySelector('input[data-tc=alerts]');
              const row = c.closest('label'); return {req: c.required, checked: c.checked, valid: f.checkValidity(), rowH: row.getBoundingClientRect().height,
              text: row.textContent, fs: [...f.querySelectorAll('input[type=text],input[type=email],input[type=tel],select')].map(e => parseFloat(getComputedStyle(e).fontSize)),
              ac: [...f.querySelectorAll('input')].map(e => e.getAttribute('autocomplete'))}; }""")
            check(a["req"] and not a["checked"], "B7 Alerts consent box is required and starts unticked", a)
            check(a["valid"] is False, "B8 Alerts form is invalid (cannot submit) with the box unticked", a)
            check(a["rowH"] >= 43.5, "B9 Alerts consent row is >= 44 px tall", a["rowH"])
            check("Listing Email Alerts" in a["text"] and "Unsubscribe any time from the link in every email." in a["text"]
                  and "204 Airport Blvd" in a["text"], "B10 Alerts consent wording is complete", a["text"])
            check(min(a["fs"]) >= 15.99, "B11 Alerts form inputs are 16 px", a["fs"])
            check({"given-name", "email", "tel"} <= set(x for x in a["ac"] if x), "B12 Alerts form fields carry autocomplete", a["ac"])
            # submit it ticked: posts express
            del posts[:]
            pg.fill("#alerts-probe [name=fname]", "Casey")
            pg.fill("#alerts-probe [name=email]", "casey.mercer@example.org")
            pg.wait_for_timeout(3500)
            pg.check("#alerts-probe input[data-tc=alerts]")
            pg.click("#alerts-probe .rf-submit")
            pg.wait_for_timeout(1200)
            mine = [x for x in posts if x.get("email") == "casey.mercer@example.org"]
            check(len(mine) == 1 and mine[0].get("marketing_optin") is True and mine[0].get("consent_type") == "express"
                  and mine[0].get("consent_at") and "/" in str(mine[0].get("consent_page", "")), "B13 Alerts submit posts express consent + time + page", mine)
            pg.close()

        # a form added after load (the home-value CMA form, popups) is picked up too, and its fields get autocomplete
        if probe:
            pg = ctx.new_page()
            pg.goto(base + "/" + probe, wait_until="load")
            pg.wait_for_timeout(1500)
            pg.evaluate("""() => { const d = document.createElement('div'); d.innerHTML = '<form id="dyn-probe"><input id="hv-first" type="text" aria-label="First name">' +
              '<input id="hv-last" type="text" aria-label="Last name"><input id="hv-email" type="email" aria-label="Email"><input id="hv-phone" type="tel" aria-label="Phone">' +
              '<button type="submit">Request my free CMA</button></form>'; document.body.appendChild(d); }""")
            pg.wait_for_timeout(800)
            d = pg.evaluate("""() => { const f = document.getElementById('dyn-probe'); return {line: !!f.querySelector('[data-consent-line]'),
              opt: !!f.querySelector('input[name=marketing_optin]:not(:checked)'), ac: [...f.querySelectorAll('input:not([type=checkbox])')].map(e => e.getAttribute('autocomplete'))}; }""")
            check(d["line"] and d["opt"], "B15 a form added after load gets the notice and the optional box", d)
            check(d["ac"] == ["given-name", "family-name", "email", "tel"], "B16 its fields get autocomplete tokens", d["ac"])
            pg.close()

        # the contact form: unticked -> implied, ticked -> express
        c = first("pages/contact.html", "contact.html")
        if c:
            pgc = ctx.new_page()
            pgc.goto(base + "/" + c, wait_until="load")
            pgc.wait_for_timeout(1500)
            has_inquiry = pgc.locator("form[data-consent-kind=inquiry]").count() > 0
            pgc.close()
            if not has_inquiry:
                NOTES.append("%s has no inquiry form: post-body checks skipped" % c)
                c = None
        if c:
            for ticked in (False, True):
                pg = ctx.new_page()
                pg.goto(base + "/" + c, wait_until="load")
                pg.wait_for_timeout(3600)   # the forms' own bot check wants > 3 s on the page
                del posts[:]
                email = "casey.mercer.%s@example.org" % ("yes" if ticked else "no")
                names = {"first_name": "Casey", "last_name": "Mercer", "name": "Casey Mercer", "email": email, "phone": "7095550142",
                         "message": "Checking the consent record, please ignore."}
                for k, v in names.items():
                    if pg.locator("#contact-form [name=%s], #contactForm [name=%s]" % (k, k)).count():
                        pg.fill("#contact-form [name=%s], #contactForm [name=%s]" % (k, k), v)
                for sel in ("#inquiry", "#license", "#subject"):
                    loc = pg.locator("#contact-form %s, #contactForm %s" % (sel, sel))
                    if loc.count():
                        tag = loc.first.evaluate("e => e.tagName")
                        if tag == "SELECT":
                            loc.first.select_option(index=1)
                        else:
                            loc.first.fill("Checking the consent record")
                if ticked:
                    pg.check("form[data-consent-kind=inquiry] input[name=marketing_optin]")
                pg.click("form[data-consent-kind=inquiry] button[type=submit], form[data-consent-kind=inquiry] .btn-submit, form[data-consent-kind=inquiry] .form-submit")
                pg.wait_for_timeout(1500)
                mine = [x for x in posts if x.get("email") == email]
                m = mine[0] if mine else {}
                check(len(mine) == 1 and m.get("marketing_optin") is ticked and m.get("consent_type") == ("express" if ticked else "implied")
                      and bool(m.get("consent_at")) and str(m.get("consent_page", "")).startswith(base),
                      "B14 contact form %s posts %s consent + time + page" % ("ticked" if ticked else "unticked", "express" if ticked else "implied"),
                      mine or posts)
                pg.close()
        br.close()
    httpd.shutdown()


def main():
    static_checks()
    try:
        browser_checks()
    except Exception as e:  # cannot run: fail closed, loudly
        log("[consent] cannot run the browser half: %r" % (e,))
        return 2
    for n in NOTES:
        log("[note] " + n)
    if FAILS:
        log("\n%d FAILURE(S): %s" % (len(FAILS), "; ".join(FAILS)[:1500]))
        return 1
    log("\nAll consent-forms checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
