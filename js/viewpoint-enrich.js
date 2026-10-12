/* viewpoint-enrich.js — public property-intelligence hydration for Viewpoint
   pages (/property/<town>/<slug>). Browser-direct (CORS confirmed open
   2026-06-06): NL Land Use Atlas zoning + flood (gov.nl.ca ArcGIS).

   COMPLIANCE — ALLOWLIST render only. Reads ONLY non-person public fields,
   rendered by an explicit allowlist. NEVER reads any owner / applicant field
   (Decision E1 + Convention #32). Crown-title layers are deliberately NOT
   queried (their APPLICANT field is a person name; that data lives only in the
   agent tool).

   MAA assessed value REMOVED 2026-06-21: MAA's website terms prohibit commercial
   republication without written permission (see DATA_LICENSES.md). Re-add the MAA
   block only once permission is on file. Atlas zoning/flood IS cleared, under the
   Open Government Licence – Newfoundland and Labrador.

   Convention #74: each source is independently graceful — a failed/empty fetch
   just omits that line; the page never errors. */
(function () {
  var box = document.querySelector('.vp-enrich');
  if (!box) return;

  var lat = parseFloat(box.getAttribute('data-lat'));
  var lng = parseFloat(box.getAttribute('data-lng'));
  var haveLL = !isNaN(lat) && !isNaN(lng);

  var data = {};   // keyed so render order is deterministic

  function esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }

  function paint() {
    var order = [
      ['zoning', 'Zoning'],
      ['flood',  'Flood risk'],
    ];
    var rows = order.filter(function (o) { return data[o[0]]; });
    if (!rows.length) {
      box.innerHTML = '<div class="vp-enrich-empty">Public land-use data isn’t available for this address yet.</div>';
      return;
    }
    box.innerHTML =
      '<dl class="vp-enrich-dl">' +
      rows.map(function (o) {
        return '<div class="vp-enrich-row"><dt>' + esc(o[1]) + '</dt><dd>' + data[o[0]] + '</dd></div>';
      }).join('') +
      '</dl>' +
      '<div class="vp-enrich-src">Source: NL Land Use Atlas (zoning, flood) — ' +
      'Contains information licensed under the Open Government Licence – Newfoundland and Labrador.</div>';
  }

  // ── NL Land Use Atlas — zoning + flood (no person fields) ─────────────
  var LUA = 'https://www.gov.nl.ca/landuseatlasmaps/rest/services/LandUseDetails/MapServer';
  function luaPoint(layer, fields) {
    return fetch(LUA + '/' + layer + '/query?geometry=' + lng + ',' + lat
                 + '&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects'
                 + '&outFields=' + encodeURIComponent(fields) + '&returnGeometry=false&f=json')
      .then(function (r) { return r.ok ? r.json() : null; });
  }

  var pZone = haveLL
    ? luaPoint(37, 'ZONETYPE,MUNICIPALITY').then(function (j) {
        var f = j && j.features && j.features[0];
        if (f && f.attributes && f.attributes.ZONETYPE) data.zoning = esc(f.attributes.ZONETYPE);
      }).catch(function () {})
    : Promise.resolve();

  // Layer 33 = 100-year (current) flood extent. Only surface when the point
  // falls inside a mapped extent (the actionable signal).
  var pFlood = haveLL
    ? luaPoint(33, 'ReturnPeriod').then(function (j) {
        if (j && j.features && j.features.length > 0) {
          data.flood = '<span class="vp-enrich-warn">Within mapped 100-year flood extent</span>';
        }
      }).catch(function () {})
    : Promise.resolve();

  Promise.all([pZone, pFlood]).then(paint);
})();
