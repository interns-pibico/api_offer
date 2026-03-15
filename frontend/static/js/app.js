/* api_offer — app.js v1
   Ofertas dashboard: load, filter, search, sort, paginate
*/
(function () {
  'use strict';

  const ROOT = window.OFFER_ROOT || '';

  // ── DOM refs ─────────────────────────────────────────────────
  const grid          = document.getElementById('ofertas-grid');
  const paginationEl  = document.getElementById('pagination');
  const searchInput   = document.getElementById('search-input');
  const fuenteFilter  = document.getElementById('fuente-filter');
  const sortFilter    = document.getElementById('sort-filter');
  const resultsInfo   = document.getElementById('results-info');

  if (!grid) return; // not on ofertas page

  // ── State ────────────────────────────────────────────────────
  let currentPage    = 1;
  let currentFuente  = '';
  let currentQ       = '';
  let currentSort    = 'descuento_desc';
  let allItems       = [];
  let searchTimeout  = null;

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
      mercadona:    'Mercadona',
      carrefour:    'Carrefour',
      alimerka:     'Alimerka',
      supermasymasonline: 'Masymas',
      masymas:      'Masymas',
      aldi:         'Aldi',
      dia:          'DIA',
      eroski:       'Eroski',
      alcampo:      'Alcampo',
      familia:      'Familia',
      gadis:        'Gadis',
      gadisline:    'Gadis',
      consum:       'Consum',
      hipercor:     'Hipercor',
      elcorteingles:'El Corte Inglés',
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

  // ── Render offer card ────────────────────────────────────────
  function renderCard(o) {
    const discPct = o.descuento_porcentaje != null
      ? Math.round(o.descuento_porcentaje) : null;

    const badgeHtml = discPct !== null
      ? `<div class="oferta-badge">-${discPct}%</div>` : '';

    const imgSrc = escHtml(o.imagen_url || '');
    const imgHtml = o.imagen_url
      ? `<img src="${imgSrc}" alt="${escHtml(o.producto_nombre)}" class="oferta-img" loading="lazy"
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
      : '';
    const placeholderStyle = o.imagen_url ? 'display:none' : '';

    const origHtml = o.precio_original != null && o.precio_original !== o.precio_oferta
      ? `<span class="oferta-precio-original">${fmtPrice(o.precio_original)}</span>`
      : '';

    const ofertaHtml = o.precio_oferta != null
      ? `<span class="oferta-precio-oferta">${fmtPrice(o.precio_oferta)}</span>`
      : '<span class="oferta-precio-oferta">—</span>';

    const verBtn = o.producto_url
      ? `<a href="${escHtml(o.producto_url)}" target="_blank" rel="noopener noreferrer" class="oferta-ver-btn">
           <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
             <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
             <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
           </svg>
           Ver
         </a>` : '';

    return `
      <div class="oferta-card">
        ${badgeHtml}
        <div class="oferta-img-wrap">
          ${imgHtml}
          <div class="oferta-img-placeholder" style="${placeholderStyle}">
            <svg class="empty-state-icon" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <path d="M21 15l-5-5L5 21"/>
            </svg>
          </div>
        </div>
        <div class="oferta-body">
          <div class="oferta-nombre" title="${escHtml(o.producto_nombre)}">${escHtml(o.producto_nombre)}</div>
          <div class="oferta-precios">${origHtml}${ofertaHtml}</div>
          <div class="oferta-meta">
            <span class="oferta-fuente" title="${escHtml(o.fuente)}">${escHtml(fuenteLabel(o.fuente))}</span>
            ${verBtn}
          </div>
        </div>
      </div>`;
  }

  // ── Sort items ────────────────────────────────────────────────
  function sortItems(items) {
    const sorted = [...items];
    switch (currentSort) {
      case 'precio_asc':
        sorted.sort((a, b) => (a.precio_oferta || 0) - (b.precio_oferta || 0));
        break;
      case 'precio_desc':
        sorted.sort((a, b) => (b.precio_oferta || 0) - (a.precio_oferta || 0));
        break;
      case 'fecha_desc':
        sorted.sort((a, b) => new Date(b.scraped_at) - new Date(a.scraped_at));
        break;
      case 'descuento_desc':
      default:
        sorted.sort((a, b) => (b.descuento_porcentaje || 0) - (a.descuento_porcentaje || 0));
    }
    return sorted;
  }

  // ── Render grid ───────────────────────────────────────────────
  function renderGrid(items) {
    if (!items || items.length === 0) {
      grid.innerHTML = `
        <div class="empty-state">
          <svg class="empty-state-icon" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
            <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/>
            <line x1="3" y1="6" x2="21" y2="6"/>
            <path d="M16 10a4 4 0 01-8 0"/>
          </svg>
          <div class="empty-state-title">Sin ofertas disponibles</div>
          <div class="empty-state-desc">No se encontraron ofertas con los filtros actuales.</div>
        </div>`;
      return;
    }
    grid.innerHTML = items.map(renderCard).join('');
  }

  // ── Load fuentes for dropdown ─────────────────────────────────
  async function loadFuentes() {
    try {
      const fuentes = await fetch(`${ROOT}/api/v1/offers/fuentes`).then(r => r.json());
      if (Array.isArray(fuentes)) {
        fuentes.forEach(f => {
          const opt = document.createElement('option');
          opt.value = f;
          opt.textContent = fuenteLabel(f);
          fuenteFilter.appendChild(opt);
        });
      }
    } catch (_) {}
  }

  // ── Render pagination ─────────────────────────────────────────
  function renderPagination(page, pages) {
    if (!paginationEl) return;
    if (pages <= 1) { paginationEl.innerHTML = ''; return; }

    const maxButtons = 7;
    let html = '';

    html += `<button class="page-btn" onclick="window._offerGoPage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>‹</button>`;

    let start = Math.max(1, page - 3);
    let end   = Math.min(pages, start + maxButtons - 1);
    start     = Math.max(1, end - maxButtons + 1);

    if (start > 1) {
      html += `<button class="page-btn" onclick="window._offerGoPage(1)">1</button>`;
      if (start > 2) html += `<span class="page-btn" style="cursor:default;opacity:0.4">…</span>`;
    }

    for (let i = start; i <= end; i++) {
      html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="window._offerGoPage(${i})">${i}</button>`;
    }

    if (end < pages) {
      if (end < pages - 1) html += `<span class="page-btn" style="cursor:default;opacity:0.4">…</span>`;
      html += `<button class="page-btn" onclick="window._offerGoPage(${pages})">${pages}</button>`;
    }

    html += `<button class="page-btn" onclick="window._offerGoPage(${page + 1})" ${page >= pages ? 'disabled' : ''}>›</button>`;

    paginationEl.innerHTML = html;
  }

  // ── Load offers ───────────────────────────────────────────────
  async function loadOfertas(page) {
    currentPage = page || 1;
    grid.innerHTML = `<div class="loading-state"><div class="spinner"></div><span>Cargando ofertas...</span></div>`;
    if (paginationEl) paginationEl.innerHTML = '';
    if (resultsInfo) resultsInfo.textContent = '';

    try {
      const params = new URLSearchParams({
        page: currentPage,
        page_size: 24,
        activo: 'true',
        sort: currentSort,
      });
      if (currentFuente) params.set('fuente', currentFuente);
      if (currentQ)      params.set('q', currentQ);

      const data = await fetch(`${ROOT}/api/v1/offers?${params}`).then(r => r.json());

      allItems = data.items || [];
      renderGrid(allItems);
      renderPagination(data.page, data.pages);

      if (resultsInfo) {
        resultsInfo.textContent = data.total > 0
          ? `${data.total.toLocaleString('es-ES')} oferta${data.total !== 1 ? 's' : ''} encontrada${data.total !== 1 ? 's' : ''}`
          : '';
      }
    } catch (e) {
      grid.innerHTML = `<div class="empty-state"><div class="empty-state-title">Error al cargar ofertas</div><div class="empty-state-desc">${escHtml(e.message)}</div></div>`;
    }
  }

  // Expose for pagination buttons
  window._offerGoPage = function(p) { loadOfertas(p); };

  // ── Events ────────────────────────────────────────────────────
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      currentQ = searchInput.value.trim();
      currentPage = 1;
      loadOfertas(1);
    }, 350);
  });

  sortFilter.addEventListener('change', () => {
    currentSort = sortFilter.value;
    currentPage = 1;
    loadOfertas(1); // server-side sort
  });

  fuenteFilter.addEventListener('change', () => {
    currentFuente = fuenteFilter.value;
    currentPage = 1;
    loadOfertas(1);
  });

  // ── Init ──────────────────────────────────────────────────────
  loadFuentes();
  loadOfertas(1);

})();
