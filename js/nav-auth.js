/* nav-auth.js — fleet-wide, state-aware "Sign in / My Account" nav entry.
 *
 * Tier-1 canonical (byte-identical across realestategander-site /
 * avalonrealestate-site / goosebayrealestate-site — Convention #15).
 * Shipped 2026-08-18 (client-portal P1).
 *
 * WHY THIS FILE EXISTS: before it, the auth entry point was fragmented —
 * saved-search.js's renderNavAuthLink() covered /listings/** only (the only
 * pages that load that 61KB file), the floating badge was CSS-disabled, and
 * the homepage / pages/* / property/** / sold pages had NO sign-in entry at
 * all. This file is ~2KB, has zero dependencies, and loads on EVERY page.
 * renderNavAuthLink()/renderBadge() were removed from saved-search.js in the
 * same ship so this file is the ONE owner of the nav auth entry.
 *
 * HOW STATE IS SNIFFED: presence of the Supabase v2 session key in
 * localStorage (sb-<project-ref>-auth-token). No auth.js / supabase-js
 * dependency — this must work on pages that load neither. A stale key
 * (expired session) renders "My Account"; the account page's own locked
 * state then offers sign-in, so the worst case is one extra click, never a
 * dead end. Convention #74: every path degrades to a plain link.
 *
 * RENDER TIMING: nav.js injects the nav via innerHTML on DOMContentLoaded,
 * which would wipe an earlier-appended <li>. nav.js therefore dispatches
 * "turner:nav-injected" at the end of injectNav() (same ship), and this file
 * re-renders on that event. It also re-renders on: DOMContentLoaded (pages
 * whose nav is baked inline and never re-injected), "storage" (another tab
 * signed in/out), "vow:unlocked" (the VOW gate just signed someone in on
 * THIS page), and TurnerAuth auth events when auth.js happens to be present
 * (progressive enhancement — never required).
 */
(function () {
  "use strict";

  var SESSION_KEY = "sb-mpzuxamyhzqsrsuelvlq-auth-token";
  var ACCOUNT_URL = "/pages/account.html";

  function signedIn() {
    try { return !!localStorage.getItem(SESSION_KEY); }
    catch (e) { return false; } // private mode / storage blocked → show "Sign in"
  }

  // The account page with ?next= this page, so signing in brings the visitor
  // back (validated to this site by auth.js; D-1009-69 item 7).
  function accountHrefWithNext() {
    if (window.location.pathname === ACCOUNT_URL) return ACCOUNT_URL;
    return ACCOUNT_URL + "?next=" + encodeURIComponent(window.location.pathname + window.location.search);
  }

  function render() {
    // Header v2's top-bar "Sign in" (drawn by nav.js): same return path.
    // Only the href changes; nav.js owns its text and look.
    if (!signedIn()) {
      var v2 = document.querySelectorAll("a.nav2-signin");
      for (var i = 0; i < v2.length; i++) {
        if ((v2[i].getAttribute("href") || "").split("?")[0] === ACCOUNT_URL) v2[i].setAttribute("href", accountHrefWithNext());
      }
    }

    var navLinks = document.querySelector(".nav-main-links");
    if (!navLinks) return; // page has no main nav (minimal templates) — no-op

    var existing = navLinks.querySelector(".nav-auth-link");
    if (existing) existing.remove();

    var authed = signedIn();
    var li = document.createElement("li");
    li.className = "nav-auth-link" + (authed ? " nav-auth-link--signed-in" : "");
    // css/auth.css refines this (separator border, padding) where loaded, but
    // most pages don't load auth.css — inline the two collision-critical
    // styles (the 2026-05-24 phone-pill overlap buffer + nowrap) so the link
    // renders acceptably on main.css typography alone.
    li.style.marginRight = "12px";

    var a = document.createElement("a");
    a.href = ACCOUNT_URL;
    // Signed out: the account page brings the visitor back here after
    // sign-in (?next=, validated to this site by auth.js; D-1009-69 item 7).
    if (!authed) a.href = accountHrefWithNext();
    a.style.whiteSpace = "nowrap";
    if (authed) {
      a.textContent = "My Account";
      a.setAttribute("aria-label", "My Account");
    } else {
      a.textContent = "Sign in";
      a.setAttribute("aria-label", "Sign in to your account");
      // Progressive enhancement: where the saved-search modal is available,
      // open it in place instead of navigating (same behavior the old
      // renderNavAuthLink had on /listings/**). The href stays as the real
      // fallback so middle-click / JS-failure still lands somewhere useful.
      a.addEventListener("click", function (e) {
        if (window.SavedSearch && typeof window.SavedSearch.openSignIn === "function") {
          e.preventDefault();
          window.SavedSearch.openSignIn();
        }
      });
    }
    li.appendChild(a);
    navLinks.appendChild(li);
  }

  // Initial render (covers baked-inline navs that never re-inject).
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }

  // nav.js just (re)wrote .nav-main-bar's innerHTML — our <li> is gone; re-add.
  document.addEventListener("turner:nav-injected", render);

  // Cross-tab sign-in/out.
  window.addEventListener("storage", function (e) {
    if (!e || !e.key || e.key === SESSION_KEY) render();
  });

  // The VOW gate signed someone in on this page.
  window.addEventListener("vow:unlocked", render);
  document.addEventListener("vow:unlocked", render);

  // Same-page sign-in/out via auth.js, when present (never required).
  function wireAuthEvents() {
    if (window.TurnerAuth && typeof window.TurnerAuth.onAuthChange === "function") {
      window.TurnerAuth.onAuthChange(function () { render(); });
      return true;
    }
    return false;
  }
  if (!wireAuthEvents()) {
    document.addEventListener("turnerauth:ready", wireAuthEvents);
  }
})();
