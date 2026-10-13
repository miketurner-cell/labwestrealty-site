/**
 * Lab West listings pages: consumer menu and footer (D-1012-34).
 *
 * Loaded by the GENERATED listings pages only, right after js/nav-config.js and before js/nav.js. It replaces the
 * recruiting menu and footer with the homes-for-sale ones. js/nav-config.js itself is untouched, so every existing page
 * (and its cache stamp) is exactly as before.
 */
(function () {
  'use strict';
  if (!window.SITE || typeof window.SITE !== 'object') return;
  var SITE = window.SITE, A = '/';
  SITE.address = 'Mike Turner, Broker of Record';
  SITE.logo = '/images/rlp-mark-plain.png'; SITE.logoW = 119; SITE.logoH = 44;
  SITE.ctaLabel = 'Call Mike';
  SITE.ctaHref = 'tel:7092567999';
  window.MENU = [
    { label: 'Home', href: A + 'index.html' },
    { label: 'Homes for Sale', href: A + 'listings/' },
    { label: 'The Market', href: A + 'labrador-west.html' },
    { label: 'Contact', href: A + 'contact.html' },
    { label: 'Join Our Team', href: A + 'become-a-realtor.html' }
  ];
  window.FOOTER = {
    copyright: '&copy; 1998&ndash;{year} Royal LePage Turner Realty (2014) Inc. Mike Turner, Broker of Record. No office in Labrador West.',
    columns: [
      { heading: 'Homes', links: [
        ['Homes for Sale', A + 'listings/'],
        ['Labrador City', A + 'listings/labrador-city/'],
        ['Wabush', A + 'listings/wabush/'],
        ['The Market', A + 'labrador-west.html']
      ] },
      { heading: 'Mike Turner, Broker', links: [
        ['709-256-7999', 'tel:7092567999'],
        ['miketurner@royallepage.ca', 'mailto:miketurner@royallepage.ca'],
        ['Contact', A + 'contact.html']
      ] },
      { heading: 'Agents', links: [
        ['This Could Be Your Territory', A + 'become-a-realtor.html'],
        ['Why Join', A + 'why-join.html'],
        ['About Turner', A + 'about-turner.html']
      ] }
    ]
  };
})();
