(function () {
  'use strict';

  const COLORS = {
    'tienda.mercadona.es':             '#04935B',   // Mercadona
    'www.carrefour.es':                '#00387b',   // Carrefour
    'supermasymasonline.com':          '#014E36',   // MasYMas
    'aldi.es':                         '#00B6ED',   // Aldi
    'www.compraonline.alcampo.es':     '#C61212',   // Alcampo
    'alimerkaonline.es':               '#FFD301',   // Alimerka
    'www.familiaonline.es':            '#B92C32',   // Familia
    'www.gadisline.com':               '#61371E',   // Gadis
  };

  const MONTH_NAMES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];

  function getColor(fuente) {
    return COLORS[fuente] || '#64748b';
  }

  function formatLabel(fuente) {
    const lower = (fuente || '').toLowerCase();
    // Handle folleto sources: "folleto:carrefour" → "Folleto Carrefour"
    if (lower.startsWith('folleto:')) {
      const superKey = lower.slice(8);
      const nameMap = {
        mercadona: 'Mercadona', carrefour: 'Carrefour', alimerka: 'Alimerka',
        masymas: 'MasYMas', aldi: 'Aldi', alcampo: 'Alcampo',
        familia: 'Familia', gadis: 'Gadis',
      };
      return 'Folleto ' + (nameMap[superKey] || superKey.replace(/\b\w/g, c => c.toUpperCase()));
    }
    if (lower.includes('mercadona')) return 'Mercadona';
    if (lower.includes('carrefour')) return 'Carrefour';
    if (lower.includes('masymas') || lower.includes('supermasymas')) return 'MasYMas';
    if (lower.includes('aldi')) return 'Aldi';
    if (lower.includes('alcampo')) return 'Alcampo';
    if (lower.includes('alimerka')) return 'Alimerka';
    if (lower.includes('familia')) return 'Familia';
    if (lower.includes('gadis')) return 'Gadis';
    return fuente;
  }

  function formatDate(iso) {
    const parts = iso.split('-');
    const day = parseInt(parts[2], 10);
    const month = parseInt(parts[1], 10) - 1;
    return day + ' ' + MONTH_NAMES[month];
  }

  function reshapeData(series, fuentes, key) {
    const allDays = [...new Set(series.map(r => r.day.slice(0, 10)))].sort();
    const labels = allDays.map(formatDate);
    const datasets = fuentes.map(fuente => {
      const map = {};
      series.filter(r => r.fuente === fuente).forEach(r => { map[r.day.slice(0, 10)] = r[key]; });
      const data = allDays.map(d => map[d] !== undefined ? map[d] : null);
      const color = getColor(fuente);
      return {
        label: formatLabel(fuente),
        data,
        backgroundColor: color + 'CC',
        hoverBackgroundColor: color,
        borderColor: color,
        borderWidth: 0,
        borderRadius: 5,
        borderSkipped: false,
        maxBarThickness: 28,
      };
    });
    return { labels, datasets };
  }

  function makeChart(ctx, chartData, yLabel, yPrefix) {
    var tooltipCallbacks = {};
    if (yPrefix) {
      tooltipCallbacks.label = function (tip) {
        var val = tip.parsed.y;
        return ' ' + tip.dataset.label + ': ' + yPrefix + (val != null ? val.toFixed(2) : '\u2014');
      };
    }

    return new Chart(ctx, {
      type: 'bar',
      data: chartData,
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 800, easing: 'easeOutQuart' },
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              usePointStyle: true,
              pointStyle: 'circle',
              font: { family: 'Figtree, sans-serif', size: 12 },
              padding: 16,
              boxWidth: 8,
            },
          },
          tooltip: {
            backgroundColor: '#1a2332',
            titleFont: { family: 'Poppins, sans-serif', size: 13, weight: '600' },
            bodyFont: { family: 'Figtree, sans-serif', size: 12 },
            cornerRadius: 8,
            padding: { top: 10, bottom: 10, left: 14, right: 14 },
            usePointStyle: true,
            boxPadding: 6,
            callbacks: tooltipCallbacks,
          },
        },
        scales: {
          x: {
            ticks: { maxRotation: 0, font: { size: 12, family: 'Figtree, sans-serif' } },
            grid: { display: false },
          },
          y: {
            title: { display: !!yLabel, text: yLabel || '', font: { size: 12, family: 'Figtree, sans-serif' } },
            ticks: {
              font: { size: 11 },
              callback: yPrefix ? function (val) { return yPrefix + val.toFixed(2); } : undefined,
            },
            grid: { color: 'rgba(0,0,0,0.06)', drawBorder: false, lineWidth: 1 },
            border: { dash: [4, 4], display: false },
            beginAtZero: false,
          },
        },
      },
    });
  }

  // ── Landing mini-chart ─────────────────────────────────────────────────────

  const landingCanvas = document.getElementById('landing-chart-activas');
  let landingChart = null;
  let landingDays = 7;

  async function fetchData(days, fuente) {
    const rootPath = window.__ROOT_PATH__ || '';
    let url = rootPath + '/api/v1/evolucion/snapshots?days=' + days;
    if (fuente) url += '&fuente=' + encodeURIComponent(fuente);
    const res = await fetch(url);
    return res.json();
  }

  async function renderLanding(days) {
    const data = await fetchData(days, null);
    const banner = document.getElementById('landing-sparse-banner');
    const uniqueDays = new Set(data.series.map(r => r.day.slice(0, 10))).size;
    if (banner) banner.style.display = uniqueDays < 3 ? '' : 'none';

    const chartData = reshapeData(data.series, data.fuentes, 'total_activas');
    if (landingChart) { landingChart.destroy(); }
    if (landingCanvas) {
      landingChart = makeChart(landingCanvas.getContext('2d'), chartData, 'Ofertas activas');
    }
  }

  if (landingCanvas) {
    renderLanding(landingDays);
    document.querySelectorAll('#landing-period-toggle .period-btn').forEach(btn => {
      btn.addEventListener('click', function () {
        document.querySelectorAll('#landing-period-toggle .period-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        landingDays = parseInt(this.dataset.days);
        renderLanding(landingDays);
      });
    });
  }

  // ── Evolucion page ─────────────────────────────────────────────────────────

  const pageToggle = document.getElementById('page-period-toggle');
  if (!pageToggle) return;

  let pageDays = 7;
  let pageFuente = null;
  let charts = {};

  function destroyCharts() {
    Object.values(charts).forEach(c => c && c.destroy());
    charts = {};
  }

  async function renderPage(days, fuente) {
    const data = await fetchData(days, fuente);
    const banner = document.getElementById('page-sparse-banner');
    const uniqueDays = new Set(data.series.map(r => r.day.slice(0, 10))).size;
    if (banner) banner.style.display = uniqueDays < 3 ? '' : 'none';

    // Update fuente pills
    const pillContainer = document.getElementById('fuente-pills');
    if (pillContainer && data.fuentes.length) {
      const existing = [...pillContainer.querySelectorAll('.fuente-pill[data-fuente]')].map(p => p.dataset.fuente);
      data.fuentes.forEach(f => {
        if (!existing.includes(f)) {
          const pill = document.createElement('button');
          pill.className = 'fuente-pill';
          pill.dataset.fuente = f;
          pill.textContent = formatLabel(f);
          pillContainer.appendChild(pill);
          pill.addEventListener('click', function () {
            pageFuente = pageFuente === f ? null : f;
            updatePills();
            renderPage(pageDays, pageFuente);
          });
        }
      });
    }

    destroyCharts();

    const c1 = document.getElementById('chart-activas');
    const c2 = document.getElementById('chart-descuento-avg');
    const c3 = document.getElementById('chart-descuento-max');
    const c4 = document.getElementById('chart-precio-avg');

    if (c1) charts.c1 = makeChart(c1.getContext('2d'), reshapeData(data.series, data.fuentes, 'total_activas'), 'Ofertas activas');
    if (c2) charts.c2 = makeChart(c2.getContext('2d'), reshapeData(data.series, data.fuentes, 'descuento_avg'), 'Descuento medio (%)');
    if (c3) charts.c3 = makeChart(c3.getContext('2d'), reshapeData(data.series, data.fuentes, 'descuento_max'), 'Mayor descuento (%)');
    if (c4) charts.c4 = makeChart(c4.getContext('2d'), reshapeData(data.series, data.fuentes, 'precio_avg'), 'Precio medio (\u20ac)', '\u20ac');
  }

  function updatePills() {
    document.querySelectorAll('.fuente-pill[data-fuente]').forEach(p => {
      p.classList.toggle('active', p.dataset.fuente === pageFuente);
    });
  }

  renderPage(pageDays, pageFuente);

  pageToggle.querySelectorAll('.period-btn').forEach(btn => {
    btn.addEventListener('click', function () {
      pageToggle.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      pageDays = parseInt(this.dataset.days);
      renderPage(pageDays, pageFuente);
    });
  });

})();
