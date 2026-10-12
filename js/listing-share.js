/**
 * Listing share widget — Turner Realty
 *
 * Wires up any element with class `lst-share-btn` whose dataset carries
 * { shareUrl, shareTitle, shareText } and turns it into a share action.
 *
 * Behaviour on click:
 *   1. If `navigator.share` is available (all modern mobile browsers,
 *      Chrome/Edge 89+ desktop, Safari 15+ desktop) — invoke the native
 *      OS share sheet so the user can pick from EVERY app they have
 *      installed (iMessage, WhatsApp, Signal, Messenger, Snapchat, etc).
 *      That is always a better UX than anything we could build.
 *   2. Otherwise — open an in-page fallback modal with direct share links
 *      to Facebook, WhatsApp, X, Email plus a Copy-Link action.
 *
 * The fallback modal is built lazily on first open (keeps the
 * generated page HTML lean). Escape / backdrop click / close button all
 * dismiss it. No dependencies — pure DOM + Clipboard API.
 */
(function () {
  'use strict';

  let modal = null;

  // ─── Modal construction (lazy) ──────────────────────────────────

  function buildModal() {
    const el = document.createElement('div');
    el.className = 'lst-share-modal';
    el.hidden = true;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-labelledby', 'lst-share-title');
    el.innerHTML = [
      '<div class="lst-share-backdrop" data-close></div>',
      '<div class="lst-share-panel" role="document">',
      '  <button type="button" class="lst-share-close" aria-label="Close" data-close>&times;</button>',
      '  <h3 id="lst-share-title">Share this listing</h3>',
      '  <div class="lst-share-targets">',
      '    <a class="lst-share-tgt" data-target="facebook" target="_blank" rel="noopener noreferrer">',
      '      <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>',
      '      <span>Facebook</span>',
      '    </a>',
      '    <a class="lst-share-tgt" data-target="whatsapp" target="_blank" rel="noopener noreferrer">',
      '      <svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22" aria-hidden="true"><path d="M20.5 3.5A11 11 0 0 0 2.1 17L1 23l6.2-1.1A11 11 0 1 0 20.5 3.5zM12 21a8.9 8.9 0 0 1-4.5-1.2l-.3-.2-3.7.7.7-3.6-.2-.3A8.9 8.9 0 1 1 21 12a8.9 8.9 0 0 1-9 9zm5-6.7c-.3-.1-1.6-.8-1.8-.9-.3-.1-.4-.1-.6.1-.2.3-.7.9-.8 1.1-.2.1-.3.2-.5.1s-1.2-.4-2.2-1.4c-.8-.7-1.4-1.6-1.5-1.9-.2-.3 0-.4.1-.5l.4-.5c.1-.2.2-.3.3-.5s.1-.3 0-.5c0-.1-.6-1.5-.8-2-.2-.5-.4-.4-.6-.4h-.5c-.2 0-.5.1-.7.3-.3.3-1 1-1 2.4s1 2.8 1.1 3 2 3 4.8 4.2c.7.3 1.2.5 1.6.6.7.2 1.3.2 1.8.1.6-.1 1.6-.7 1.9-1.3.3-.6.3-1.2.2-1.3s-.3-.2-.6-.3z"/></svg>',
      '      <span>WhatsApp</span>',
      '    </a>',
      '    <a class="lst-share-tgt" data-target="twitter" target="_blank" rel="noopener noreferrer">',
      '      <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20" aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>',
      '      <span>X</span>',
      '    </a>',
      '    <a class="lst-share-tgt" data-target="email">',
      '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="22" height="22" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><polyline points="3,7 12,13 21,7"/></svg>',
      '      <span>Email</span>',
      '    </a>',
      '    <button type="button" class="lst-share-tgt lst-share-copy" data-target="copy">',
      '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="22" height="22" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
      '      <span>Copy Link</span>',
      '    </button>',
      '  </div>',
      '  <p class="lst-share-url" data-url></p>',
      '  <div class="lst-share-toast" role="status" aria-live="polite" hidden>Link copied</div>',
      '</div>'
    ].join('');

    document.body.appendChild(el);
    el.addEventListener('click', onModalClick);
    return el;
  }

  // ─── Open / close ──────────────────────────────────────────────

  function openFallback(url, title, text) {
    if (!modal) modal = buildModal();

    // Stash current share payload on the modal itself — handlers read it.
    modal.dataset.url = url;
    modal.dataset.title = title;
    modal.dataset.text = text;
    modal.querySelector('[data-url]').textContent = url;

    // Wire the per-platform hrefs. Each share URL uses the platform's
    // canonical sharing endpoint — no app IDs, no tokens required.
    const enc = encodeURIComponent;
    const combined = text ? text + ' ' + url : url;
    modal.querySelector('[data-target=facebook]').href =
      'https://www.facebook.com/sharer/sharer.php?u=' + enc(url);
    modal.querySelector('[data-target=whatsapp]').href =
      'https://wa.me/?text=' + enc(combined);
    modal.querySelector('[data-target=twitter]').href =
      'https://twitter.com/intent/tweet?url=' + enc(url) + '&text=' + enc(text || title);
    modal.querySelector('[data-target=email]').href =
      'mailto:?subject=' + enc(title) + '&body=' + enc((text ? text + '\n\n' : '') + url);

    modal.hidden = false;
    document.body.style.overflow = 'hidden';

    const close = modal.querySelector('.lst-share-close');
    if (close) close.focus();
  }

  function closeModal() {
    if (!modal) return;
    modal.hidden = true;
    document.body.style.overflow = '';
  }

  // ─── Copy link (with a graceful fallback for old browsers) ──────

  async function copyLink() {
    const url = modal.dataset.url;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
        showToast('Link copied');
        return;
      }
      throw new Error('clipboard API unavailable');
    } catch (err) {
      // Older-browser path — select the URL text so the user can press
      // ⌘C / Ctrl-C themselves.
      const p = modal.querySelector('[data-url]');
      const range = document.createRange();
      range.selectNode(p);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      showToast('Link selected — press \u2318/Ctrl+C');
    }
  }

  function showToast(msg) {
    const t = modal.querySelector('.lst-share-toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(function () { t.hidden = true; }, 2000);
  }

  // ─── Event delegation ──────────────────────────────────────────

  function onModalClick(e) {
    if (e.target.closest('[data-close]')) {
      e.preventDefault();
      closeModal();
      return;
    }
    if (e.target.closest('.lst-share-copy')) {
      e.preventDefault();
      copyLink();
    }
    // All other share targets are plain <a target="_blank"> links — let
    // the browser open them normally. We close the modal after a short
    // delay so the new tab/window has time to kick off.
    if (e.target.closest('.lst-share-tgt') && !e.target.closest('.lst-share-copy')) {
      setTimeout(closeModal, 150);
    }
  }

  function onShareClick(e) {
    const btn = e.target.closest('.lst-share-btn');
    if (!btn) return;
    e.preventDefault();

    const url = btn.dataset.shareUrl || window.location.href;
    const title = btn.dataset.shareTitle || document.title;
    const text = btn.dataset.shareText || title;

    if (navigator.share) {
      navigator.share({ title: title, text: text, url: url }).catch(function (err) {
        // AbortError = user dismissed the native sheet; stay quiet.
        // Any other error (NotAllowedError, permissions, etc.) → give
        // them the fallback modal instead of a silent failure.
        if (err && err.name !== 'AbortError') {
          openFallback(url, title, text);
        }
      });
    } else {
      openFallback(url, title, text);
    }
  }

  document.addEventListener('click', onShareClick);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal && !modal.hidden) closeModal();
  });
})();
