/* api_offer — comparar.js v3
   Price comparator: winner card (green) + otras opciones grid
   Relevance filter: query must appear in first 3 words of product name
*/
(function () {
  'use strict';

  const ROOT = window.OFFER_ROOT || '';

  // ── DOM refs ─────────────────────────────────────────────────
  const searchInput    = document.getElementById('compare-search');
  const resultsSection = document.getElementById('compare-results');
  const summaryEl      = document.getElementById('compare-summary');
  const winnerEl       = document.getElementById('compare-winner');
  const restTitleEl    = document.getElementById('compare-rest-title');
  const restGridEl     = document.getElementById('compare-rest-grid');
  const suggestionsWrap = document.getElementById('suggestions-wrap');
  const suggestionsGrid = document.getElementById('suggestions-grid');

  if (!searchInput) return;

  let searchTimeout = null;

  // ── Helpers ──────────────────────────────────────────────────
  function fmtPrice(v) {
    if (v == null) return '—';
    return new Intl.NumberFormat('es-ES', {
      style: 'currency', currency: 'EUR', minimumFractionDigits: 2
    }).format(v);
  }

  function escHtml(s) {
    if (!s) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fuenteLabel(fuente) {
    const map = {
      mercadona:          'Mercadona',
      carrefour:          'Carrefour',
      alimerka:           'Alimerka',
      supermasymasonline: 'Masymas',
      masymas:            'Masymas',
      aldi:               'Aldi',
      dia:                'DIA',
      eroski:             'Eroski',
      alcampo:            'Alcampo',
      familia:            'Familia',
      gadis:              'Gadis',
      gadisline:          'Gadis',
      consum:             'Consum',
      hipercor:           'Hipercor',
      elcorteingles:      'El Corte Inglés',
    };
    const lower = (fuente || '').toLowerCase();
    for (const [key, name] of Object.entries(map)) {
      if (lower.includes(key)) return name;
    }
    return (fuente || '')
      .replace(/^(www\.|tienda\.|shop\.|online\.)/, '')
      .split('.')[0]
      .replace(/-/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }

  // ── Relevance filter ─────────────────────────────────────────
  // The first query word must appear within the first 3 words of the product name.
  // This prevents "Tortitas de maíz con yogur" from showing when searching "yogur".
  function normalize(s) {
    return (s || '').toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, ''); // strip accents
  }

  function isRelevant(productName, q) {
    const queryWords = normalize(q).split(/\s+/).filter(w => w.length > 1);
    if (!queryWords.length) return true;
    const nameWords = normalize(productName).split(/\s+/);
    const first3 = nameWords.slice(0, 3).join(' ');
    // All query words must be present somewhere in the name,
    // AND the first query word must appear in the first 3 words.
    return first3.includes(queryWords[0]);
  }

  // ── Render winner card (full-width green) ────────────────────
  function renderWinner(o) {
    const discPct = o.descuento_porcentaje != null ? Math.round(o.descuento_porcentaje) : null;
    const discHtml = discPct !== null
      ? `<span class="compare-winner-discount">-${discPct}%</span>` : '';
    const origHtml = o.precio_original != null
      ? `<span class="compare-winner-original">${escHtml(fmtPrice(o.precio_original))}</span>` : '';
    const imgHtml = o.imagen_url
      ? `<img class="compare-winner-img" src="${escHtml(o.imagen_url)}" alt="${escHtml(o.producto_nombre)}" loading="lazy" onerror="this.parentElement.innerHTML='<svg width=48 height=48 fill=none stroke=%23d1d5db stroke-width=1.5 viewBox=\\'0 0 24 24\\'><rect x=3 y=3 width=18 height=18 rx=2/><circle cx=8.5 cy=8.5 r=1.5/><path d=\\'M21 15l-5-5L5 21\\'/></svg>'">`
      : `<svg width="48" height="48" fill="none" stroke="#d1d5db" stroke-width="1.5" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>`;
    const verHtml = o.producto_url
      ? `<a href="${escHtml(o.producto_url)}" target="_blank" rel="noopener" class="compare-winner-ver">Ver oferta →</a>` : '';

    return `
      <div class="compare-winner-img-wrap">${imgHtml}</div>
      <div class="compare-winner-body">
        <div class="compare-winner-badge">🏆 Mejor precio</div>
        <div class="compare-winner-nombre">${escHtml(o.producto_nombre)}</div>
        <div class="compare-winner-precios">
          <span class="compare-winner-precio">${escHtml(fmtPrice(o.precio_oferta))}</span>
          ${origHtml}
          ${discHtml}
        </div>
        <div class="compare-winner-meta">
          <span class="oferta-fuente">${escHtml(fuenteLabel(o.fuente))}</span>
          ${verHtml}
        </div>
      </div>`;
  }

  // ── Render regular card ──────────────────────────────────────
  function renderCard(o) {
    const discPct = o.descuento_porcentaje != null ? Math.round(o.descuento_porcentaje) : null;
    const badgeHtml = discPct !== null
      ? `<div class="oferta-badge">-${discPct}%</div>` : '';
    const imgHtml = o.imagen_url
      ? `<img class="oferta-img" src="${escHtml(o.imagen_url)}" alt="${escHtml(o.producto_nombre)}" loading="lazy" onerror="this.style.display='none'">`
      : `<div class="oferta-img-placeholder"><svg width="48" height="48" fill="none" stroke="#d1d5db" stroke-width="1.5" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>`;
    const origHtml = o.precio_original != null
      ? `<span class="oferta-precio-original">${escHtml(fmtPrice(o.precio_original))}</span>` : '';
    const verHtml = o.producto_url
      ? `<a href="${escHtml(o.producto_url)}" target="_blank" rel="noopener" class="oferta-ver-btn">Ver →</a>` : '';

    return `
      <div class="oferta-card">
        ${badgeHtml}
        <div class="oferta-img-wrap">${imgHtml}</div>
        <div class="oferta-body">
          <div class="oferta-nombre">${escHtml(o.producto_nombre)}</div>
          <div class="oferta-precios">
            ${origHtml}
            <span class="oferta-precio-oferta">${escHtml(fmtPrice(o.precio_oferta))}</span>
          </div>
          <div class="oferta-meta">
            <span class="oferta-fuente">${escHtml(fuenteLabel(o.fuente))}</span>
            ${verHtml}
          </div>
        </div>
      </div>`;
  }

  // ── Render suggestion card ───────────────────────────────────
  function renderSuggestion(o) {
    const imgHtml = o.imagen_url
      ? `<img class="oferta-img" src="${escHtml(o.imagen_url)}" alt="${escHtml(o.producto_nombre)}" loading="lazy" onerror="this.style.display='none'">`
      : `<div class="oferta-img-placeholder"><svg width="36" height="36" fill="none" stroke="#d1d5db" stroke-width="1.5" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>`;
    const discPct = o.descuento_porcentaje != null ? Math.round(o.descuento_porcentaje) : null;

    return `
      <div class="suggestion-card" data-nombre="${escHtml(o.producto_nombre)}">
        <div class="oferta-img-wrap">${imgHtml}</div>
        <div class="suggestion-card-body">
          <div class="suggestion-nombre">${escHtml(o.producto_nombre)}</div>
          <div class="suggestion-meta">
            <span class="oferta-fuente">${escHtml(fuenteLabel(o.fuente))}</span>
            ${discPct !== null ? `<span class="suggestion-chip">-${discPct}%</span>` : '<span class="suggestion-chip">Comparar →</span>'}
          </div>
        </div>
      </div>`;
  }

  // ── Show/hide sections ───────────────────────────────────────
  function showResults() {
    resultsSection.style.display = '';
    if (suggestionsWrap) suggestionsWrap.style.display = 'none';
  }

  function showSuggestions() {
    resultsSection.style.display = 'none';
    if (suggestionsWrap) suggestionsWrap.style.display = '';
    summaryEl.textContent = '';
    winnerEl.innerHTML = '';
    winnerEl.style.display = 'none';
    restTitleEl.style.display = 'none';
    restGridEl.innerHTML = '';
  }

  // ── Load suggestions ─────────────────────────────────────────
  async function loadSuggestions() {
    if (!suggestionsGrid) return;
    try {
      const resp = await fetch(`${ROOT}/api/v1/offers?page_size=24&activo=true`);
      if (!resp.ok) return;
      const data = await resp.json();
      const items = data.items || [];
      if (!items.length) return;
      suggestionsGrid.innerHTML = items.map(renderSuggestion).join('');

      suggestionsGrid.querySelectorAll('.suggestion-card').forEach(card => {
        card.addEventListener('click', () => {
          const nombre = card.dataset.nombre || '';
          const allWords = nombre.trim().split(/\s+/);
          // Use first 1-2 meaningful words (skip very short words like articles)
          const meaningful = allWords.filter(w => w.length > 2);
          const q = meaningful.slice(0, 2).join(' ') || allWords[0] || nombre;
          searchInput.value = q;
          doSearch(q);
          searchInput.focus();
        });
      });
    } catch (e) {
      // silently ignore
    }
  }

  // ── Search ───────────────────────────────────────────────────
  async function doSearch(q) {
    if (q.length < 2) {
      showSuggestions();
      return;
    }

    showResults();
    summaryEl.textContent = 'Buscando…';
    winnerEl.style.display = 'none';
    restTitleEl.style.display = 'none';
    restGridEl.innerHTML = '';

    try {
      const resp = await fetch(`${ROOT}/api/v1/offers/compare?q=${encodeURIComponent(q)}&limit=40`);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();

      // Filter: only results where the query appears in the first 3 words
      const relevant = data.results.filter(o => isRelevant(o.producto_nombre, q));

      if (!relevant.length) {
        summaryEl.textContent = '';
        winnerEl.innerHTML = `
          <div class="empty-state" style="width:100%">
            <div class="empty-state-icon">
              <svg width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
                <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
              </svg>
            </div>
            <div class="empty-state-title">Sin resultados</div>
            <div class="empty-state-desc">No se encontraron ofertas para "<strong>${escHtml(q)}</strong>"</div>
            <a href="${ROOT}/ofertas" class="btn btn-primary btn-sm" style="margin-top:.5rem">Ver todas las ofertas</a>
          </div>`;
        winnerEl.style.display = 'flex';
        winnerEl.style.background = 'none';
        winnerEl.style.border = 'none';
        return;
      }

      const fuentes = new Set(relevant.map(r => fuenteLabel(r.fuente)));
      summaryEl.textContent = `${relevant.length} variante${relevant.length !== 1 ? 's' : ''} en ${fuentes.size} supermercado${fuentes.size !== 1 ? 's' : ''}`;

      // Winner (cheapest, already sorted ASC by API)
      winnerEl.innerHTML = renderWinner(relevant[0]);
      winnerEl.style.display = '';
      winnerEl.style.background = '';
      winnerEl.style.border = '';

      // Rest
      const rest = relevant.slice(1);
      if (rest.length) {
        restTitleEl.style.display = '';
        restGridEl.innerHTML = rest.map(renderCard).join('');
      }

    } catch (e) {
      summaryEl.textContent = 'Error al buscar. Inténtalo de nuevo.';
    }
  }

  // ── Event listeners ──────────────────────────────────────────
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = searchInput.value.trim();
    if (q.length < 2) {
      showSuggestions();
      return;
    }
    searchTimeout = setTimeout(() => doSearch(q), 400);
  });

  searchInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      clearTimeout(searchTimeout);
      doSearch(searchInput.value.trim());
    }
  });

  // ── Init ─────────────────────────────────────────────────────
  showSuggestions();
  loadSuggestions();

})();
