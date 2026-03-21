/* api_offer — listas.js v2
   Shopping list generator: NL prompt → ingredients → best offers
   + saved lists (requires auth)
*/
(function () {
  'use strict';

  var ROOT = window.OFFER_ROOT || '';

  var promptInput = document.getElementById('listas-prompt');
  var generateBtn = document.getElementById('listas-btn');
  var loadingEl   = document.getElementById('listas-loading');
  var resultsEl   = document.getElementById('listas-results');
  var titleEl     = document.getElementById('listas-title');
  var itemsEl     = document.getElementById('listas-items');
  var summaryEl   = document.getElementById('listas-summary');
  var errorEl     = document.getElementById('listas-error');
  var errorMsg    = document.getElementById('listas-error-msg');

  // Auth-aware elements
  var authBanner    = document.getElementById('listas-auth-banner');
  var savedSection  = document.getElementById('saved-lists-section');
  var savedGrid     = document.getElementById('saved-lists-grid');
  var savedEmpty    = document.getElementById('saved-lists-empty');
  var savedCount    = document.getElementById('saved-lists-count');
  var saveBtn       = document.getElementById('listas-save-btn');

  // Detail modal
  var detailOverlay = document.getElementById('list-detail-overlay');
  var detailName    = document.getElementById('list-detail-name');
  var detailDesc    = document.getElementById('list-detail-desc');
  var detailItems   = document.getElementById('list-detail-items');
  var detailClose   = document.getElementById('list-detail-close');
  var detailDelete  = document.getElementById('list-detail-delete');

  // Save dialog
  var saveOverlay   = document.getElementById('save-dialog-overlay');
  var saveClose     = document.getElementById('save-dialog-close');
  var saveNameInput = document.getElementById('save-list-name');
  var saveDescInput = document.getElementById('save-list-desc');
  var saveSubmit    = document.getElementById('save-dialog-submit');
  var saveError     = document.getElementById('save-dialog-error');

  if (!promptInput) return;

  // Last generated ingredients (for saving)
  var lastGenerated = null;
  var openDetailId = null;

  // ─── Helpers ───

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
      .replace(/"/g, '&quot;');
  }

  function fuenteLabel(fuente) {
    var map = {
      mercadona: 'Mercadona', carrefour: 'Carrefour', alimerka: 'Alimerka',
      supermasymasonline: 'Masymas', masymas: 'Masymas', aldi: 'Aldi',
      alcampo: 'Alcampo', familia: 'Familia', gadis: 'Gadis', gadisline: 'Gadis',
    };
    var lower = (fuente || '').toLowerCase();
    if (lower.startsWith('folleto:')) {
      var k = lower.slice(8);
      return 'Folleto ' + (map[k] || k);
    }
    for (var key in map) {
      if (lower.includes(key)) return map[key];
    }
    return fuente || '';
  }

  function authHeaders() {
    var token = window.offerAuth && window.offerAuth.token;
    if (!token) return {};
    return { 'Authorization': 'Bearer ' + token };
  }

  function hideAll() {
    loadingEl.style.display = 'none';
    resultsEl.style.display = 'none';
    errorEl.style.display = 'none';
  }

  function fmtDate(iso) {
    try {
      var d = new Date(iso);
      return d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
    } catch (e) { return ''; }
  }

  // ─── Auth-aware init ───

  function initAuth() {
    if (window.offerAuth && window.offerAuth.isLoggedIn) {
      if (authBanner) authBanner.style.display = 'none';
      if (savedSection) savedSection.style.display = '';
      loadSavedLists();
    } else {
      if (authBanner) authBanner.style.display = '';
      if (savedSection) savedSection.style.display = 'none';
    }
  }

  // Register callback for when auth check completes
  if (window.offerAuth) {
    if (window.offerAuth.user !== undefined && window.offerAuth.user !== null) {
      // Auth already resolved
      initAuth();
    }
    window.offerAuth.onReady.push(initAuth);
  }

  // ─── Saved lists ───

  async function loadSavedLists() {
    try {
      var resp = await fetch(ROOT + '/api/v1/lists', { headers: authHeaders() });
      if (!resp.ok) return;
      var lists = await resp.json();
      renderSavedLists(lists);
    } catch (e) {
      console.error('Failed to load saved lists', e);
    }
  }

  function renderSavedLists(lists) {
    if (!savedGrid) return;
    savedCount.textContent = lists.length + '/4';

    if (lists.length === 0) {
      savedGrid.innerHTML = '';
      savedEmpty.style.display = '';
      return;
    }

    savedEmpty.style.display = 'none';
    var html = '';
    for (var sl of lists) {
      html += '<div class="saved-list-card" data-id="' + sl.id + '">' +
        '<div class="saved-list-card-name">' + escHtml(sl.name) + '</div>' +
        (sl.description ? '<div class="saved-list-card-desc">' + escHtml(sl.description) + '</div>' : '') +
        '<div class="saved-list-card-meta">' +
          '<span>' + sl.item_count + ' ingrediente' + (sl.item_count !== 1 ? 's' : '') + '</span>' +
          '<span>' + fmtDate(sl.updated_at) + '</span>' +
        '</div>' +
      '</div>';
    }
    savedGrid.innerHTML = html;

    // Click handlers
    savedGrid.querySelectorAll('.saved-list-card').forEach(function (card) {
      card.addEventListener('click', function () {
        openDetail(parseInt(this.dataset.id));
      });
    });
  }

  async function openDetail(id) {
    openDetailId = id;
    try {
      var resp = await fetch(ROOT + '/api/v1/lists/' + id, { headers: authHeaders() });
      if (!resp.ok) return;
      var list = await resp.json();
      renderDetail(list);
    } catch (e) {
      console.error('Failed to load list detail', e);
    }
  }

  function renderDetail(list) {
    // Editable name
    detailName.innerHTML = '<input type="text" class="detail-edit-name" id="detail-edit-name" value="' + escHtml(list.name) + '">';
    // Editable description
    detailDesc.innerHTML = '<input type="text" class="detail-edit-desc" id="detail-edit-desc" value="' + escHtml(list.description || '') + '" placeholder="Descripción (opcional)">';
    detailDesc.style.display = '';

    // Items with remove buttons
    var html = '';
    for (var item of list.items) {
      var qty = [item.quantity, item.unit].filter(Boolean).join(' ');
      html += '<div class="list-detail-item">' +
        '<span class="list-detail-item-name">' + escHtml(item.ingredient_name) + '</span>' +
        (qty ? '<span class="list-detail-item-qty">' + escHtml(qty) + '</span>' : '') +
        '<button class="list-detail-item-remove" data-item-id="' + item.id + '" title="Quitar">' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6L6 18M6 6l12 12"/></svg>' +
        '</button>' +
      '</div>';
    }
    detailItems.innerHTML = html || '<p style="color:var(--text-muted)">Sin ingredientes</p>';

    // Remove item handlers
    detailItems.querySelectorAll('.list-detail-item-remove').forEach(function(btn) {
      btn.addEventListener('click', async function(e) {
        e.stopPropagation();
        var itemId = this.dataset.itemId;
        try {
          var resp = await fetch(ROOT + '/api/v1/lists/' + openDetailId + '/items/' + itemId, {
            method: 'DELETE', headers: authHeaders(),
          });
          if (resp.ok || resp.status === 204) {
            this.closest('.list-detail-item').remove();
            loadSavedLists();
          }
        } catch(err) { console.error(err); }
      });
    });

    detailOverlay.style.display = '';
  }

  // Save edits on close (name/description changes)
  async function saveDetailEdits() {
    if (!openDetailId) return;
    var nameInput = document.getElementById('detail-edit-name');
    var descInput = document.getElementById('detail-edit-desc');
    if (!nameInput) return;
    var newName = nameInput.value.trim();
    var newDesc = descInput ? descInput.value.trim() : '';
    if (!newName) return;
    try {
      var hdrs = authHeaders();
      hdrs['Content-Type'] = 'application/json';
      await fetch(ROOT + '/api/v1/lists/' + openDetailId, {
        method: 'PUT', headers: hdrs,
        body: JSON.stringify({ name: newName, description: newDesc || null }),
      });
      loadSavedLists();
    } catch(e) { console.error(e); }
  }

  if (detailClose) {
    detailClose.addEventListener('click', function () {
      saveDetailEdits();
      detailOverlay.style.display = 'none';
      openDetailId = null;
    });
  }

  if (detailDelete) {
    detailDelete.addEventListener('click', async function () {
      if (!openDetailId) return;
      if (!confirm('¿Eliminar esta lista?')) return;
      try {
        var resp = await fetch(ROOT + '/api/v1/lists/' + openDetailId, {
          method: 'DELETE',
          headers: authHeaders(),
        });
        if (resp.ok || resp.status === 204) {
          detailOverlay.style.display = 'none';
          openDetailId = null;
          loadSavedLists();
        }
      } catch (e) {
        console.error('Failed to delete list', e);
      }
    });
  }

  // Close overlays on outside click
  if (detailOverlay) {
    detailOverlay.addEventListener('click', function (e) {
      if (e.target === detailOverlay) {
        saveDetailEdits();
        detailOverlay.style.display = 'none';
        openDetailId = null;
      }
    });
  }

  // ─── Generate ───

  async function generate() {
    var prompt = promptInput.value.trim();
    if (!prompt) return;

    hideAll();
    loadingEl.style.display = '';
    generateBtn.disabled = true;
    lastGenerated = null;

    try {
      var resp = await fetch(ROOT + '/api/v1/shopping/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt }),
      });

      if (!resp.ok) {
        var err = {};
        try { err = await resp.json(); } catch (e) {}
        throw new Error(err.detail || 'Error ' + resp.status);
      }

      var data = await resp.json();
      lastGenerated = data;
      renderResults(data);
    } catch (e) {
      hideAll();
      errorEl.style.display = '';
      errorMsg.textContent = e.message;
    } finally {
      generateBtn.disabled = false;
    }
  }

  function renderResults(data) {
    hideAll();
    resultsEl.style.display = '';

    var ingredients = data.ingredients || [];
    titleEl.textContent = ingredients.length + ' ingrediente' + (ingredients.length !== 1 ? 's' : '') +
      ' encontrado' + (ingredients.length !== 1 ? 's' : '');

    // Show save button if logged in
    if (saveBtn) {
      saveBtn.style.display = (window.offerAuth && window.offerAuth.isLoggedIn) ? '' : 'none';
    }

    var html = '';
    for (var item of ingredients) {
      var offer = item.best_offer;
      var offerHtml = offer
        ? '<div class="lista-item-offer">' +
            '<div class="lista-item-price">' + fmtPrice(offer.precio_oferta) + '</div>' +
            '<div class="lista-item-super">' + escHtml(fuenteLabel(offer.fuente)) + '</div>' +
          '</div>'
        : '<div class="lista-item-offer"><span class="lista-item-noffer">Sin ofertas</span></div>';

      var itemPrice = (offer && offer.precio_oferta) ? offer.precio_oferta : 0;
      html += '<div class="lista-item">' +
        '<input type="checkbox" class="lista-item-check" checked data-price="' + itemPrice + '">' +
        '<div class="lista-item-name">' + escHtml(item.nombre) + '</div>' +
        '<div class="lista-item-qty">' + escHtml(item.cantidad || '') + ' ' + escHtml(item.unidad || '') + '</div>' +
        offerHtml +
      '</div>';
    }
    itemsEl.innerHTML = html;

    // Store budget for recalculation
    var currentBudget = data.budget;

    // Recalculate total from checked items
    function recalcTotal() {
      var total = 0;
      itemsEl.querySelectorAll('.lista-item-check').forEach(function(cb) {
        if (cb.checked) total += parseFloat(cb.dataset.price) || 0;
      });
      updateSummary(total, currentBudget);
    }

    function updateSummary(total, budget) {
      if (total > 0 || budget != null) {
        summaryEl.style.display = '';
        var html = '<div class="listas-summary-label">Total estimado</div>' +
          '<div class="listas-summary-total">' + fmtPrice(total) + '</div>';
        if (budget != null) {
          if (total <= budget) {
            html += '<div class="listas-budget-ok">Dentro del presupuesto de ' + fmtPrice(budget) + '</div>';
          } else {
            html += '<div class="listas-budget-over">Supera el presupuesto de ' + fmtPrice(budget) +
              ' en ' + fmtPrice(total - budget) + '</div>';
          }
        }
        summaryEl.innerHTML = html;
      } else {
        summaryEl.style.display = 'none';
      }
    }

    // Listen for checkbox changes
    itemsEl.querySelectorAll('.lista-item-check').forEach(function(cb) {
      cb.addEventListener('change', function() {
        // Visual: dim unchecked items
        var item = this.closest('.lista-item');
        if (item) item.style.opacity = this.checked ? '1' : '0.4';
        recalcTotal();
      });
    });

    // Initial summary
    updateSummary(data.total_estimated || 0, currentBudget);
  }

  // ─── Save list ───

  if (saveBtn) {
    saveBtn.addEventListener('click', function () {
      if (!lastGenerated) return;
      saveNameInput.value = '';
      saveDescInput.value = '';
      saveError.style.display = 'none';
      saveOverlay.style.display = '';
      saveNameInput.focus();
    });
  }

  if (saveClose) {
    saveClose.addEventListener('click', function () {
      saveOverlay.style.display = 'none';
    });
  }

  if (saveOverlay) {
    saveOverlay.addEventListener('click', function (e) {
      if (e.target === saveOverlay) saveOverlay.style.display = 'none';
    });
  }

  if (saveSubmit) {
    saveSubmit.addEventListener('click', async function () {
      var name = saveNameInput.value.trim();
      if (!name) {
        saveError.textContent = 'Escribe un nombre para la lista';
        saveError.style.display = '';
        return;
      }
      if (!lastGenerated || !lastGenerated.ingredients) return;

      var items = lastGenerated.ingredients.map(function (ing) {
        return {
          ingredient_name: ing.nombre,
          quantity: ing.cantidad || null,
          unit: ing.unidad || null,
        };
      });

      saveSubmit.disabled = true;
      saveError.style.display = 'none';

      try {
        var hdrs = authHeaders();
        hdrs['Content-Type'] = 'application/json';
        var resp = await fetch(ROOT + '/api/v1/lists', {
          method: 'POST',
          headers: hdrs,
          body: JSON.stringify({
            name: name,
            description: saveDescInput.value.trim() || null,
            items: items,
          }),
        });

        if (!resp.ok) {
          var err = {};
          try { err = await resp.json(); } catch (e) {}
          saveError.textContent = err.detail || 'Error al guardar';
          saveError.style.display = '';
          return;
        }

        saveOverlay.style.display = 'none';
        loadSavedLists();
      } catch (e) {
        saveError.textContent = 'Error de conexión';
        saveError.style.display = '';
      } finally {
        saveSubmit.disabled = false;
      }
    });
  }

  // ─── Event listeners ───

  generateBtn.addEventListener('click', generate);
  promptInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') generate();
  });

})();
