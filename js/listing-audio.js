/**
 * listing-audio.js — "Hear about this home" (Ship 4, 2026-09-10).
 *
 * Every [data-listen] button carries data-site/data-mls/data-sig/data-script
 * already computed + HMAC-signed server-side at page-build time
 * (tools/listing_script.py + tools/ddf-generate-pages.py:build_listen_section).
 * This script never builds or edits that text — it only reads it verbatim
 * off the DOM and POSTs it to netlify/functions/listing-audio.ts, which
 * re-verifies the signature before doing anything. A tampered data-script
 * (e.g. via devtools) fails that check server-side; nothing here needs to
 * defend against that itself.
 *
 * Preview gating: a .lst-listen--preview section stays hidden (CSS) unless
 * the page URL carries ?listen=1 — lets Mike test the real feature on a
 * real listing via a private link before LISTING_AUDIO flips to "on" for
 * everyone (LISTING_AUDIO=preview at generation time).
 */
(function () {
  "use strict";

  function showPreviewSections() {
    var params;
    try {
      params = new URLSearchParams(window.location.search);
    } catch (e) {
      return;
    }
    if (params.get("listen") !== "1") return;
    var sections = document.querySelectorAll(".lst-listen--preview");
    for (var i = 0; i < sections.length; i++) {
      sections[i].style.display = "";
    }
  }

  function trackPlay(mls, cached) {
    if (typeof window.gtag !== "function") return;
    try {
      window.gtag("event", "audio_play", { surface: "listing", mls: mls, cached: !!cached });
    } catch (e) {
      /* analytics must never break the button */
    }
  }

  function setStatus(section, text) {
    var status = section.querySelector(".lst-listen-status");
    if (!status) return;
    if (text) {
      status.textContent = text;
      status.hidden = false;
    } else {
      status.hidden = true;
    }
  }

  function handleClick(btn) {
    var section = btn.closest(".lst-listen");
    var audio = section ? section.querySelector(".lst-listen-audio") : null;
    if (!section || !audio) return;

    // Already have audio loaded — toggle play/pause instead of re-fetching.
    if (audio.src && !audio.hidden) {
      if (audio.paused) {
        audio.play();
      } else {
        audio.pause();
      }
      return;
    }

    var site = btn.getAttribute("data-site") || "";
    var mls = btn.getAttribute("data-mls") || "";
    var sig = btn.getAttribute("data-sig") || "";
    var script = btn.getAttribute("data-script") || "";
    if (!site || !mls || !sig || !script) return;

    btn.disabled = true;
    setStatus(section, "Loading narration…");

    fetch("/.netlify/functions/listing-audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site: site, mls: mls, sig: sig, script: script }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (result) {
        btn.disabled = false;
        if (!result.ok || !result.data || !result.data.ok || !result.data.url) {
          setStatus(section, (result.data && result.data.reason) || "Couldn't load the narration right now.");
          return;
        }
        setStatus(section, "");
        audio.src = result.data.url;
        audio.hidden = false;
        audio.play();
        btn.setAttribute("data-playing", "1");
        trackPlay(mls, !!result.data.cached);
      })
      .catch(function () {
        btn.disabled = false;
        setStatus(section, "Couldn't load the narration right now — try again in a moment.");
      });
  }

  function init() {
    showPreviewSections();
    document.addEventListener("click", function (ev) {
      var btn = ev.target.closest && ev.target.closest("[data-listen]");
      if (btn) handleClick(btn);
    });
    document.addEventListener(
      "play",
      function (ev) {
        var audio = ev.target;
        if (!audio.classList || !audio.classList.contains("lst-listen-audio")) return;
        var btn = audio.closest(".lst-listen") && audio.closest(".lst-listen").querySelector("[data-listen]");
        if (btn) btn.setAttribute("data-playing", "1");
      },
      true
    );
    document.addEventListener(
      "pause",
      function (ev) {
        var audio = ev.target;
        if (!audio.classList || !audio.classList.contains("lst-listen-audio")) return;
        var btn = audio.closest(".lst-listen") && audio.closest(".lst-listen").querySelector("[data-listen]");
        if (btn) btn.removeAttribute("data-playing");
      },
      true
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
