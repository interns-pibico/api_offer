/* folletos.js v11 — Flyer extraction with page selector + SSE progress */
(function () {
  'use strict';

  const ROOT = window.OFFER_ROOT || '';
  let apiKey = '';
  let selectedFile = null;
  let totalPages = 0;
  let selectedPages = new Set();

  /* ── Auth ─────────────────────────────────────────────────── */
  window.authenticate = async function () {
    const input = document.getElementById('api-key-input');
    const key = input.value.trim();
    if (!key) return;

    try {
      const res = await fetch(`${ROOT}/api/v1/flyers/check/carrefour`, {
        headers: { 'X-API-Key': key }
      });
      if (res.ok) {
        apiKey = key;
        document.getElementById('auth-gate').style.display = 'none';
        document.getElementById('flyer-tool').style.display = 'block';
      } else {
        showAuthError('API Key inválida');
      }
    } catch {
      showAuthError('Error de conexión');
    }
  };

  function showAuthError(msg) {
    const el = document.getElementById('auth-error');
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 3000);
  }

  /* ── File handling ────────────────────────────────────────── */
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');

  if (dropZone) {
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => {
      dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) setFile(fileInput.files[0]);
    });
  }

  async function setFile(file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      alert('Solo se permiten archivos PDF');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      alert('El archivo supera los 50 MB');
      return;
    }
    selectedFile = file;
    document.getElementById('file-info').style.display = 'flex';
    document.getElementById('file-name').textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
    dropZone.style.display = 'none';

    // Get thumbnails from backend
    try {
      const fd = new FormData();
      fd.append('file', file);
      const loadingEl = document.getElementById('pages-loading');
      const container = document.getElementById('page-selector');
      container.style.display = 'block';
      if (loadingEl) loadingEl.style.display = 'flex';

      const res = await fetch(`${ROOT}/api/v1/flyers/thumbnails`, {
        method: 'POST',
        headers: { 'X-API-Key': apiKey },
        body: fd,
      });
      if (loadingEl) loadingEl.style.display = 'none';
      if (res.ok) {
        const data = await res.json();
        totalPages = data.pages;
        buildPageSelector(totalPages, data.thumbnails);
      }
    } catch { /* ignore */ }
  }

  window.clearFile = function () {
    selectedFile = null;
    fileInput.value = '';
    totalPages = 0;
    selectedPages.clear();
    document.getElementById('file-info').style.display = 'none';
    document.getElementById('page-selector').style.display = 'none';
    dropZone.style.display = '';
  };

  /* ── Page selector ────────────────────────────────────────── */
  function buildPageSelector(count, thumbnails) {
    const container = document.getElementById('page-selector');
    const grid = document.getElementById('pages-grid');

    selectedPages.clear();
    for (let i = 1; i <= count; i++) selectedPages.add(i);

    let html = '';
    for (let i = 0; i < count; i++) {
      const pageNum = i + 1;
      const thumb = thumbnails && thumbnails[i]
        ? `<img src="data:image/jpeg;base64,${thumbnails[i]}" alt="Pág ${pageNum}" draggable="false">`
        : `<div class="flyer-thumb-placeholder">${pageNum}</div>`;
      html += `
        <div class="flyer-thumb selected" data-page="${pageNum}" onclick="togglePage(${pageNum}, this)">
          ${thumb}
          <div class="flyer-thumb-overlay">
            <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="3" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <span class="flyer-thumb-num">${pageNum}</span>
        </div>
      `;
    }
    grid.innerHTML = html;
    container.style.display = 'block';
    updatePagesInput();
  }

  window.togglePage = function (num, el) {
    if (selectedPages.has(num)) {
      selectedPages.delete(num);
      el.classList.remove('selected');
    } else {
      selectedPages.add(num);
      el.classList.add('selected');
    }
    updatePagesInput();
  };

  window.selectAllPages = function () {
    selectedPages.clear();
    for (let i = 1; i <= totalPages; i++) selectedPages.add(i);
    document.querySelectorAll('.flyer-thumb').forEach(b => b.classList.add('selected'));
    updatePagesInput();
  };

  window.deselectAllPages = function () {
    selectedPages.clear();
    document.querySelectorAll('.flyer-thumb').forEach(b => b.classList.remove('selected'));
    updatePagesInput();
  };

  function updatePagesInput() {
    // Build compact string: "1-5,7,9-12"
    const sorted = [...selectedPages].sort((a, b) => a - b);
    const label = document.getElementById('pages-count-label');
    label.textContent = `(${sorted.length} de ${totalPages} seleccionadas)`;

    if (sorted.length === 0) {
      document.getElementById('pages-input').value = '';
      return;
    }
    if (sorted.length === totalPages) {
      document.getElementById('pages-input').value = '';
      return;
    }

    const ranges = [];
    let start = sorted[0], end = sorted[0];
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i] === end + 1) {
        end = sorted[i];
      } else {
        ranges.push(start === end ? `${start}` : `${start}-${end}`);
        start = end = sorted[i];
      }
    }
    ranges.push(start === end ? `${start}` : `${start}-${end}`);
    document.getElementById('pages-input').value = ranges.join(',');
  }

  /* ── Helpers ──────────────────────────────────────────────── */
  function getFormData(forPreview) {
    if (!selectedFile) { alert('Selecciona un PDF primero'); return null; }
    const fd = new FormData();
    fd.append('file', selectedFile);
    fd.append('supermarket', document.getElementById('supermarket-select').value);
    if (forPreview) {
      fd.append('page', '1');
    } else {
      if (selectedPages.size === 0) { alert('Selecciona al menos una página'); return null; }
      const pages = document.getElementById('pages-input').value;
      if (pages) fd.append('pages', pages);
      fd.append('save', document.getElementById('save-check').checked ? 'true' : 'false');
    }
    return fd;
  }

  function setButtons(disabled) {
    document.getElementById('preview-btn').disabled = disabled;
    document.getElementById('extract-btn').disabled = disabled;
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  /* ── Progress bar ─────────────────────────────────────────── */
  function showProgress(page, total, productsFound) {
    const card = document.getElementById('progress-card');
    card.style.display = 'block';

    const pct = Math.round((page / total) * 100);
    document.getElementById('progress-inner').innerHTML = `
      <div class="flyer-progress-header">
        <span>${page} de ${total} páginas procesadas</span>
        <span>${pct}%</span>
      </div>
      <div class="flyer-progress-bar-track">
        <div class="flyer-progress-bar-fill" style="width: ${pct}%"></div>
      </div>
      <div class="flyer-progress-details">
        <span>${productsFound} productos en este lote</span>
      </div>
    `;
  }

  function showProgressProcessing(page, pageEnd, total) {
    const card = document.getElementById('progress-card');
    card.style.display = 'block';

    const pctStart = Math.round(((page - 1) / total) * 100);
    const label = pageEnd && pageEnd > page
      ? `Procesando páginas ${page}-${pageEnd} de ${total}...`
      : `Procesando página ${page} de ${total}...`;
    document.getElementById('progress-inner').innerHTML = `
      <div class="flyer-progress-header">
        <span>${label}</span>
        <span>${pctStart}%</span>
      </div>
      <div class="flyer-progress-bar-track">
        <div class="flyer-progress-bar-fill flyer-progress-bar-fill--active" style="width: ${pctStart}%"></div>
      </div>
      <div class="flyer-progress-details">
        <span class="flyer-progress-waiting"><span class="spinner-sm"></span> Esperando respuesta de IA...</span>
      </div>
    `;
  }

  function showProgressSaving() {
    document.getElementById('progress-inner').innerHTML = `
      <div class="flyer-progress-header">
        <span>Guardando en base de datos...</span>
        <span>100%</span>
      </div>
      <div class="flyer-progress-bar-track">
        <div class="flyer-progress-bar-fill" style="width: 100%"></div>
      </div>
    `;
  }

  function hideProgress() {
    document.getElementById('progress-card').style.display = 'none';
  }

  /* ── Preview (single page, no SSE) ──────────────────────── */
  window.runPreview = async function () {
    const fd = getFormData(true);
    if (!fd) return;
    setButtons(true);
    hideResults();

    const card = document.getElementById('progress-card');
    card.style.display = 'block';
    document.getElementById('progress-inner').innerHTML = `
      <div class="flyer-progress-details">
        <span class="flyer-progress-waiting"><span class="spinner-sm"></span> Extrayendo página 1 con IA...</span>
      </div>
    `;

    try {
      const res = await fetch(`${ROOT}/api/v1/flyers/extract/preview`, {
        method: 'POST',
        headers: { 'X-API-Key': apiKey },
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error en preview');
      renderPreview(data);
    } catch (err) {
      showError(err.message);
    } finally {
      hideProgress();
      setButtons(false);
    }
  };

  /* ── Extract (SSE streaming) ────────────────────────────── */
  window.runExtract = async function () {
    const fd = getFormData(false);
    if (!fd) return;
    const save = document.getElementById('save-check').checked;
    const supermarket = document.getElementById('supermarket-select').value;

    setButtons(true);
    hideResults();

    const card = document.getElementById('progress-card');
    card.style.display = 'block';
    document.getElementById('progress-inner').innerHTML = `
      <div class="flyer-progress-details">
        <span class="flyer-progress-waiting"><span class="spinner-sm"></span> Iniciando extracción...</span>
      </div>
    `;

    try {
      const res = await fetch(`${ROOT}/api/v1/flyers/extract`, {
        method: 'POST',
        headers: { 'X-API-Key': apiKey },
        body: fd,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || `Error ${res.status}`);
      }

      // Read SSE stream
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let doneData = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop();

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const jsonStr = part.slice(6);
          let event;
          try { event = JSON.parse(jsonStr); } catch { continue; }

          if (event.type === 'processing') {
            showProgressProcessing(event.page, event.page_end, event.total);
          } else if (event.type === 'page_done') {
            showProgress(event.page, event.total, event.products_found);
          } else if (event.type === 'done') {
            showProgressSaving();
            doneData = event;
          }
        }
      }

      hideProgress();
      if (doneData) {
        renderExtract(doneData);

        // Handle duplicates — ask user if they want to update
        if (doneData.duplicates > 0 && save) {
          const names = doneData.duplicate_names.slice(0, 5).join('\n  - ');
          const more = doneData.duplicates > 5 ? `\n  ...y ${doneData.duplicates - 5} más` : '';
          const ok = confirm(
            `${doneData.duplicates} producto(s) ya existían en la base de datos:\n  - ${names}${more}\n\n` +
            `¿Deseas actualizar sus precios con los datos del folleto?`
          );
          if (ok) {
            // Collect duplicate products from all pages
            const dupeNames = new Set(doneData.duplicate_names);
            const dupeProducts = [];
            for (const page of doneData.pages) {
              for (const p of page.products) {
                if (dupeNames.has(p.producto_nombre)) {
                  dupeProducts.push(p);
                }
              }
            }
            try {
              const upRes = await fetch(`${ROOT}/api/v1/flyers/update-duplicates`, {
                method: 'POST',
                headers: { 'X-API-Key': apiKey, 'Content-Type': 'application/json' },
                body: JSON.stringify({ fuente: doneData.source, products: dupeProducts }),
              });
              if (upRes.ok) {
                const upData = await upRes.json();
                alert(`${upData.updated} producto(s) actualizados correctamente.`);
              }
            } catch { /* ignore */ }
          }
        }
      } else {
        showError('No se recibió respuesta del servidor');
      }

    } catch (err) {
      hideProgress();
      showError(err.message);
    } finally {
      setButtons(false);
    }
  };

  /* ── Render results ───────────────────────────────────────── */
  function hideResults() {
    document.getElementById('results-card').style.display = 'none';
    document.getElementById('results-errors').style.display = 'none';
  }

  function renderPreview(data) {
    const card = document.getElementById('results-card');
    card.style.display = 'block';

    document.getElementById('results-stats').innerHTML = `
      <div class="flyer-stat"><span class="flyer-stat-val">${data.products.length}</span><span class="flyer-stat-lbl">Productos</span></div>
      <div class="flyer-stat"><span class="flyer-stat-val">Pág. ${data.page}</span><span class="flyer-stat-lbl">Página</span></div>
    `;

    document.getElementById('results-pages').innerHTML = renderProductTable(data.products, data.page);
  }

  function renderExtract(data) {
    const card = document.getElementById('results-card');
    card.style.display = 'block';

    let statsHtml = `
      <div class="flyer-stat"><span class="flyer-stat-val">${data.total_products_found}</span><span class="flyer-stat-lbl">Productos</span></div>
      <div class="flyer-stat"><span class="flyer-stat-val">${data.pages_processed}/${data.total_pages}</span><span class="flyer-stat-lbl">Páginas</span></div>
      <div class="flyer-stat"><span class="flyer-stat-val">${data.saved}</span><span class="flyer-stat-lbl">Nuevos guardados</span></div>
    `;
    if (data.duplicates > 0) {
      statsHtml += `<div class="flyer-stat"><span class="flyer-stat-val">${data.duplicates}</span><span class="flyer-stat-lbl">Ya existían</span></div>`;
    }
    statsHtml += `<div class="flyer-stat"><span class="flyer-stat-val">${data.source}</span><span class="flyer-stat-lbl">Fuente</span></div>`;
    document.getElementById('results-stats').innerHTML = statsHtml;

    let html = '';
    for (const page of data.pages) {
      html += `<h4 class="flyer-page-title">Página ${page.page} — ${page.products_found} productos</h4>`;
      html += renderProductTable(page.products, page.page);
    }
    document.getElementById('results-pages').innerHTML = html;

    if (data.errors && data.errors.length) {
      const errEl = document.getElementById('results-errors');
      errEl.style.display = 'block';
      errEl.innerHTML = `<h4 class="flyer-err-title">Errores</h4><ul>${data.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`;
    }
  }

  function renderProductTable(products, page) {
    if (!products.length) return `<p class="text-muted">No se encontraron productos en la página ${page}.</p>`;
    let rows = products.map((p, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${esc(p.producto_nombre)}</td>
        <td class="num">${p.precio_oferta != null ? p.precio_oferta.toFixed(2) + ' &euro;' : '—'}</td>
        <td class="num">${p.precio_original != null ? p.precio_original.toFixed(2) + ' &euro;' : '—'}</td>
        <td class="num">${p.descuento_porcentaje != null ? p.descuento_porcentaje.toFixed(0) + '%' : '—'}</td>
      </tr>
    `).join('');

    return `
      <div class="flyer-table-wrap">
        <table class="flyer-table">
          <thead><tr><th>#</th><th>Producto</th><th class="num">Precio oferta</th><th class="num">Precio original</th><th class="num">Dto.</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  function showError(msg) {
    const card = document.getElementById('results-card');
    card.style.display = 'block';
    document.getElementById('results-stats').innerHTML = '';
    document.getElementById('results-pages').innerHTML = `<div class="flyer-error">${esc(msg)}</div>`;
  }

  /* ── Enter key on API key input ──────────────────────────── */
  const keyInput = document.getElementById('api-key-input');
  if (keyInput) keyInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') authenticate(); });

})();
