/* landing.js v2 — api_offer landing page interactivity */
(function () {
  'use strict';

  var ROOT = window.OFFER_ROOT || '';

  /* ── Add landing-page class to body for scoped background ─── */
  document.body.classList.add('landing-page');

  /* ── Stat: total ofertas activas ──────────────────────────── */
  fetch(ROOT + '/api/v1/offers?activo=true&page=1&page_size=1')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var el = document.getElementById('stat-total');
      if (el && data.total != null) {
        animateNumber(el, data.total);
      }
    })
    .catch(function () {});

  /* ── Stat: número de supermercados (agrupados) ──────────── */
  fetch(ROOT + '/api/v1/offers/fuentes')
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var el = document.getElementById('stat-fuentes');
      if (el && Array.isArray(data)) {
        var keys = ['mercadona','carrefour','alimerka','masymas','aldi','alcampo','familia','gadis'];
        var seen = {};
        for (var i = 0; i < data.length; i++) {
          var lower = data[i].toLowerCase();
          for (var j = 0; j < keys.length; j++) {
            if (lower.indexOf(keys[j]) !== -1) { seen[keys[j]] = true; break; }
          }
        }
        var count = Object.keys(seen).length;
        if (count > 0) animateNumber(el, count);
      }
    })
    .catch(function () {});

  /* ── Animated number counter ──────────────────────────────── */
  function animateNumber(el, target) {
    var start = 0;
    var duration = 1200;
    var startTime = null;

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      // ease-out cubic
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = Math.round(start + (target - start) * eased);
      el.textContent = current.toLocaleString('es-ES');
      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = target.toLocaleString('es-ES');
      }
    }

    requestAnimationFrame(step);
  }

})();
