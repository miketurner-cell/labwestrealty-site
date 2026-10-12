/**
 * Royal LePage Turner Realty — Listing photo lightbox
 *
 * Self-contained, dependency-free. Activates on any element with
 *   data-lightbox-gallery='[{"url":"...","caption":"..."}, ...]'
 * by attaching click handlers to descendant <a data-lb-index="N">
 * elements and to any <button data-lightbox-open="N"> that lives
 * inside the same parent as the gallery (e.g. .lst-gallery-wrap).
 *
 * Features
 *   - Keyboard nav: ← → Home End Esc
 *   - Touch swipe (left/right)
 *   - Counter "4 / 22"
 *   - Caption display
 *   - Image preload (±1 from current)
 *   - Focus trap, restores focus on close
 *   - Body scroll lock while open
 *   - Graceful fallback: anchors still open the photo in a new tab
 *     if JS fails to load or run
 *
 * Wiring expected from the generator:
 *   <div class="lst-gallery-wrap">
 *     <div class="lst-gallery" data-lightbox-gallery="[...]">
 *       <a href="..." data-lb-index="0">...</a>
 *       <a href="..." data-lb-index="1">...</a>
 *       ...
 *     </div>
 *     <button class="lst-view-all-btn" data-lightbox-open="0">View all 22 photos</button>
 *   </div>
 */
(function() {
  'use strict';

  // ── Injected styles ──────────────────────────────────────────────
  var STYLES = ''
    + '.rlpt-lb-backdrop {'
    + '  position: fixed; inset: 0; z-index: 99999;'
    + '  background: rgba(0,0,0,0.96);'
    + '  display: none; flex-direction: column;'
    + '  opacity: 0; transition: opacity .2s ease;'
    + "  font-family: 'Roboto', sans-serif;"
    + '}'
    + '.rlpt-lb-backdrop.is-open { opacity: 1; }'
    + '.rlpt-lb-topbar {'
    + '  flex: 0 0 auto;'
    + '  display: flex; justify-content: space-between; align-items: center;'
    + '  padding: 14px 20px; color: #fff;'
    + '}'
    + '.rlpt-lb-counter { font-size: 0.95rem; font-weight: 500; letter-spacing: 0.3px; }'
    + '.rlpt-lb-close {'
    + '  background: transparent; border: none; color: #fff;'
    + '  font-size: 28px; line-height: 1; cursor: pointer;'
    + '  padding: 4px 12px; border-radius: 4px;'
    + '  transition: background .15s ease;'
    + '}'
    + '.rlpt-lb-close:hover, .rlpt-lb-close:focus {'
    + '  background: rgba(255,255,255,0.12); outline: none;'
    + '}'
    + '.rlpt-lb-stage {'
    + '  flex: 1 1 auto; position: relative;'
    + '  display: flex; align-items: center; justify-content: center;'
    + '  overflow: hidden; user-select: none;'
    + '}'
    + '.rlpt-lb-img {'
    + '  max-width: 100%; max-height: 100%;'
    + '  object-fit: contain; display: block;'
    + '  transition: opacity .15s ease;'
    + '}'
    + '.rlpt-lb-img.is-loading { opacity: 0.25; }'
    + '.rlpt-lb-spinner {'
    + '  position: absolute; width: 48px; height: 48px;'
    + '  border: 4px solid rgba(255,255,255,0.18); border-top-color: #fff;'
    + '  border-radius: 50%; animation: rlpt-lb-spin .9s linear infinite;'
    + '  display: none;'
    + '}'
    + '.rlpt-lb-stage.is-loading .rlpt-lb-spinner { display: block; }'
    + '@keyframes rlpt-lb-spin { to { transform: rotate(360deg); } }'
    + '.rlpt-lb-nav {'
    + '  position: absolute; top: 50%; transform: translateY(-50%);'
    + '  background: rgba(0,0,0,0.45); border: none; color: #fff;'
    + '  width: 52px; height: 52px; border-radius: 50%;'
    + '  font-size: 28px; line-height: 1; cursor: pointer;'
    + '  display: flex; align-items: center; justify-content: center;'
    + '  transition: background .15s ease, transform .1s ease;'
    + '}'
    + '.rlpt-lb-nav:hover, .rlpt-lb-nav:focus {'
    + '  background: rgba(0,0,0,0.78); outline: none;'
    + '}'
    + '.rlpt-lb-nav:active { transform: translateY(-50%) scale(0.94); }'
    + '.rlpt-lb-prev { left: 16px; }'
    + '.rlpt-lb-next { right: 16px; }'
    + '.rlpt-lb-nav[disabled] { opacity: 0.3; cursor: not-allowed; }'
    + '.rlpt-lb-caption {'
    + '  flex: 0 0 auto; color: #ddd; text-align: center;'
    + '  padding: 12px 20px 20px; font-size: 0.9rem; min-height: 1em;'
    + '}'
    + '.rlpt-lb-caption:empty { padding: 0; min-height: 0; }'
    + '@media (max-width: 600px) {'
    + '  .rlpt-lb-nav { width: 44px; height: 44px; font-size: 22px; }'
    + '  .rlpt-lb-prev { left: 8px; }'
    + '  .rlpt-lb-next { right: 8px; }'
    + '  .rlpt-lb-topbar { padding: 10px 14px; }'
    + '}'
    + 'body.rlpt-lb-no-scroll { overflow: hidden; }';

  function injectStyles() {
    if (document.getElementById('rlpt-lb-styles')) return;
    var s = document.createElement('style');
    s.id = 'rlpt-lb-styles';
    s.textContent = STYLES;
    document.head.appendChild(s);
  }

  // ── Lightbox state (single shared modal) ─────────────────────────
  var state = {
    photos: [],
    index: 0,
    backdrop: null, img: null, counter: null, caption: null,
    prevBtn: null, nextBtn: null, stage: null, closeBtn: null,
    lastFocus: null, touchStartX: null, touchStartY: null,
  };

  function buildModal() {
    if (state.backdrop) return;
    var bd = document.createElement('div');
    bd.className = 'rlpt-lb-backdrop';
    bd.setAttribute('role', 'dialog');
    bd.setAttribute('aria-modal', 'true');
    bd.setAttribute('aria-label', 'Property photo gallery');
    bd.innerHTML =
      '<div class="rlpt-lb-topbar">' +
        '<div class="rlpt-lb-counter" aria-live="polite"></div>' +
        '<button type="button" class="rlpt-lb-close" aria-label="Close gallery">\u00D7</button>' +
      '</div>' +
      '<div class="rlpt-lb-stage">' +
        '<button type="button" class="rlpt-lb-nav rlpt-lb-prev" aria-label="Previous photo">\u2039</button>' +
        '<img class="rlpt-lb-img" alt="">' +
        '<div class="rlpt-lb-spinner" aria-hidden="true"></div>' +
        '<button type="button" class="rlpt-lb-nav rlpt-lb-next" aria-label="Next photo">\u203A</button>' +
      '</div>' +
      '<div class="rlpt-lb-caption" aria-live="polite"></div>';

    document.body.appendChild(bd);

    state.backdrop = bd;
    state.counter  = bd.querySelector('.rlpt-lb-counter');
    state.closeBtn = bd.querySelector('.rlpt-lb-close');
    state.stage    = bd.querySelector('.rlpt-lb-stage');
    state.img      = bd.querySelector('.rlpt-lb-img');
    state.prevBtn  = bd.querySelector('.rlpt-lb-prev');
    state.nextBtn  = bd.querySelector('.rlpt-lb-next');
    state.caption  = bd.querySelector('.rlpt-lb-caption');

    state.closeBtn.addEventListener('click', close);
    state.prevBtn.addEventListener('click', function(e) { e.stopPropagation(); prev(); });
    state.nextBtn.addEventListener('click', function(e) { e.stopPropagation(); next(); });
    bd.addEventListener('click', function(e) {
      if (e.target === bd || e.target === state.stage || e.target === state.caption) close();
    });
    state.img.addEventListener('load', function() {
      state.img.classList.remove('is-loading');
      state.stage.classList.remove('is-loading');
    });
    state.img.addEventListener('error', function() {
      state.img.classList.remove('is-loading');
      state.stage.classList.remove('is-loading');
    });

    // Touch swipe
    state.stage.addEventListener('touchstart', function(e) {
      if (e.touches.length !== 1) return;
      state.touchStartX = e.touches[0].clientX;
      state.touchStartY = e.touches[0].clientY;
    }, { passive: true });
    state.stage.addEventListener('touchend', function(e) {
      if (state.touchStartX == null) return;
      var dx = e.changedTouches[0].clientX - state.touchStartX;
      var dy = e.changedTouches[0].clientY - state.touchStartY;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) {
        if (dx < 0) next(); else prev();
      }
      state.touchStartX = null;
      state.touchStartY = null;
    });
  }

  function render() {
    if (!state.photos.length) return;
    var n = state.photos.length;
    var i = state.index;
    var photo = state.photos[i];
    state.img.classList.add('is-loading');
    state.stage.classList.add('is-loading');
    state.img.src = photo.url;
    state.img.alt = photo.caption || ('Listing photo ' + (i + 1));
    state.counter.textContent = (i + 1) + ' / ' + n;
    state.caption.textContent = photo.caption || '';
    // Mike 2026-05-12: gallery wraps around — Next from last → first,
    // Prev from first → last. Buttons stay enabled at the endpoints so
    // the wrap-around action is always visible to the user.
    state.prevBtn.disabled = false;
    state.nextBtn.disabled = false;
    // Preload neighbours (wrapping). When n === 1 the wrap-around resolves
    // to the same photo, which is a harmless self-preload.
    if (n > 1) {
      var nx = new Image(); nx.src = state.photos[(i + 1) % n].url;
      var pv = new Image(); pv.src = state.photos[(i - 1 + n) % n].url;
    }
  }

  // Wrap-around navigation — last → first on next(), first → last on prev().
  function next() {
    if (!state.photos.length) return;
    state.index = (state.index + 1) % state.photos.length;
    render();
  }
  function prev() {
    if (!state.photos.length) return;
    state.index = (state.index - 1 + state.photos.length) % state.photos.length;
    render();
  }

  function open(photos, startIndex) {
    if (!photos || !photos.length) return;
    buildModal();
    state.photos = photos;
    state.index = Math.max(0, Math.min(startIndex || 0, photos.length - 1));
    state.lastFocus = document.activeElement;
    state.backdrop.style.display = 'flex';
    void state.backdrop.offsetWidth;            // force reflow so transition fires
    state.backdrop.classList.add('is-open');
    document.body.classList.add('rlpt-lb-no-scroll');
    document.addEventListener('keydown', onKey);
    render();
    setTimeout(function() { state.closeBtn.focus(); }, 0);
  }

  function close() {
    if (!state.backdrop) return;
    state.backdrop.classList.remove('is-open');
    document.body.classList.remove('rlpt-lb-no-scroll');
    document.removeEventListener('keydown', onKey);
    setTimeout(function() {
      state.backdrop.style.display = 'none';
      state.img.removeAttribute('src');
    }, 200);
    if (state.lastFocus && state.lastFocus.focus) {
      try { state.lastFocus.focus(); } catch (e) { /* ignore */ }
    }
  }

  function onKey(e) {
    switch (e.key) {
      case 'Escape':     e.preventDefault(); close(); break;
      case 'ArrowRight': e.preventDefault(); next();  break;
      case 'ArrowLeft':  e.preventDefault(); prev();  break;
      case 'Home':       e.preventDefault(); state.index = 0; render(); break;
      case 'End':        e.preventDefault(); state.index = state.photos.length - 1; render(); break;
      case 'Tab':
        e.preventDefault();
        var focusables = [state.closeBtn, state.prevBtn, state.nextBtn]
          .filter(function(el) { return el && !el.disabled; });
        if (!focusables.length) return;
        var idx = focusables.indexOf(document.activeElement);
        var nextIdx = e.shiftKey
          ? (idx <= 0 ? focusables.length - 1 : idx - 1)
          : ((idx + 1) % focusables.length);
        focusables[nextIdx].focus();
        break;
    }
  }

  // ── Init: wire each gallery on the page ──────────────────────────
  function init() {
    injectStyles();
    var galleries = document.querySelectorAll('[data-lightbox-gallery]');
    Array.prototype.forEach.call(galleries, function(gal) {
      var photos;
      try { photos = JSON.parse(gal.getAttribute('data-lightbox-gallery')); }
      catch (e) { return; }
      if (!Array.isArray(photos) || !photos.length) return;

      // Tile clicks
      var tiles = gal.querySelectorAll('a[data-lb-index]');
      Array.prototype.forEach.call(tiles, function(a) {
        a.addEventListener('click', function(e) {
          // Allow command/ctrl-click and middle-click to follow the href
          if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;
          e.preventDefault();
          var idx = parseInt(a.getAttribute('data-lb-index'), 10) || 0;
          open(photos, idx);
        });
      });

      // "View all" CTA — must live in same parent as the gallery
      var parent = gal.parentElement;
      if (!parent) return;
      var openBtns = parent.querySelectorAll('[data-lightbox-open]');
      Array.prototype.forEach.call(openBtns, function(btn) {
        btn.addEventListener('click', function(e) {
          e.preventDefault();
          var idx = parseInt(btn.getAttribute('data-lightbox-open'), 10) || 0;
          open(photos, idx);
        });
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose for ad-hoc invocation
  window.RLPTLightbox = { open: open, close: close };
})();
