// Teleport drawer & overlay out of .page-enter so position:fixed works correctly
document.addEventListener('DOMContentLoaded', () => {
  ['bondDrawer', 'drawerOverlay'].forEach(id => {
    const el = document.getElementById(id);
    if (el) document.body.appendChild(el);
  });
});

function openDrawer(bondId, notesVal) {
  document.getElementById('bondDrawer').classList.add('open');
  document.getElementById('drawerOverlay').classList.add('open');
  document.body.style.overflow = 'hidden';
  const notesEl = document.getElementById('bondNotes');
  const drawerTitle = document.querySelector('.drawer-title');
  if (bondId) {
    document.getElementById('bondDrawer').dataset.editId = bondId;
    if (notesEl) notesEl.value = notesVal || '';
    if (drawerTitle) drawerTitle.textContent = 'Редактировать заметку';
    document.getElementById('addBondBtn').textContent = 'Сохранить заметку';
    document.getElementById('addBondBtn').onclick = saveNoteOnly;
  } else {
    delete document.getElementById('bondDrawer').dataset.editId;
    if (notesEl) notesEl.value = '';
    if (drawerTitle) drawerTitle.textContent = 'Добавить облигацию';
    document.getElementById('addBondBtn').textContent = 'Добавить в портфель';
    document.getElementById('addBondBtn').onclick = function () {
      document.getElementById('addBondForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    };
    setTimeout(() => document.getElementById('bondIsin')?.focus(), 350);
  }
}

function closeDrawer() {
  document.getElementById('bondDrawer').classList.remove('open');
  document.getElementById('drawerOverlay').classList.remove('open');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

async function saveNoteOnly() {
  const drawer = document.getElementById('bondDrawer');
  const bondId = drawer.dataset.editId;
  if (!bondId) return;
  const notes = document.getElementById('bondNotes')?.value || '';
  const btn = document.getElementById('addBondBtn');
  btn.disabled = true; btn.textContent = 'Сохранение…';
  try {
    const res = await window.Common.csrfFetch(`/api/portfolio/${bondId}/notes`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes }),
    });
    const data = await res.json();
    if (res.ok) {
      window.Common.showToast('Заметка сохранена');
      const noteBtn = document.querySelector(`[data-note-btn="${bondId}"]`);
      if (noteBtn) noteBtn.title = data.notes ? data.notes : 'Добавить заметку';
      if (noteBtn) noteBtn.style.opacity = data.notes ? '1' : '0.35';
      closeDrawer();
    } else {
      window.Common.showSystemMessage(data.message || 'Ошибка', true);
    }
  } finally {
    btn.disabled = false; btn.textContent = 'Сохранить заметку';
  }
}

function filterBondsTable(q) {
  const rows = document.querySelectorAll('#bonds-table-body tr[data-name]');
  const s = q.toLowerCase();
  rows.forEach(r => {
    const show = !s || r.dataset.name?.toLowerCase().includes(s) || r.dataset.isin?.toLowerCase().includes(s);
    r.style.display = show ? '' : 'none';
  });
}

// ── Sharpe Ratio ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  fetch('/api/portfolio/sharpe')
    .then(r => r.json())
    .then(data => {
      const el = document.getElementById('sharpeValue');
      const sub = document.getElementById('sharpeSub');
      const sampleEl = document.getElementById('sharpeSampleSize');
      if (!el) return;
      if (data.sharpe == null) {
        el.textContent = '—';
        if (sub) sub.textContent = data.reason || '';
        return;
      }
      const sharpe = parseFloat(data.sharpe);
      el.textContent = sharpe.toFixed(2);
      el.style.color = sharpe >= 1 ? 'var(--emerald-500)' : sharpe >= 0 ? 'var(--text-info)' : '#ef4444';
      if (sub) sub.textContent = `Доход: ${data.mean_return_pct}% · Волат.: ${data.volatility_pct}%`;
      if (sampleEl) sampleEl.textContent = ` · ${data.sample_size} сделок`;
    })
    .catch(() => {});
});

// ── Compare two bonds ─────────────────────────────────────────────────────────

let _compareChart = null;

function runCompare() {
  const isin1 = (document.getElementById('compareIsin1')?.value || '').trim().toUpperCase();
  const isin2 = (document.getElementById('compareIsin2')?.value || '').trim().toUpperCase();
  const range  = document.getElementById('compareRange')?.value || 'month';

  if (!isin1 || !isin2) { window.Common.showToast('Введите оба ISIN', true); return; }
  if (isin1 === isin2)  { window.Common.showToast('ISIN должны быть разными', true); return; }

  const loadEl   = document.getElementById('compare-loading');
  const emptyEl  = document.getElementById('compareEmpty');
  const legendEl = document.getElementById('compareLegend');
  if (loadEl)   loadEl.style.display = 'block';
  if (emptyEl)  emptyEl.style.display = 'none';
  if (legendEl) legendEl.style.display = 'none';

  fetch(`/api/portfolio/compare?isin1=${isin1}&isin2=${isin2}&range=${range}`)
    .then(r => r.json())
    .then(data => {
      if (loadEl) loadEl.style.display = 'none';
      if (!data.status || data.status !== 'success') {
        window.Common.showToast(data.message || 'Ошибка загрузки', true);
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }
      const labels = data.labels || [];
      const d1 = data.bond1?.data || [];
      const d2 = data.bond2?.data || [];
      if (!labels.length) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }

      const n1El = document.getElementById('compareName1');
      const n2El = document.getElementById('compareName2');
      if (n1El) n1El.textContent = data.bond1?.name || isin1;
      if (n2El) n2El.textContent = data.bond2?.name || isin2;
      if (legendEl) legendEl.style.display = 'flex';

      _onChartJsReady(() => {
        const ctx = document.getElementById('compareChart');
        if (!ctx) return;
        if (_compareChart) _compareChart.destroy();
        _compareChart = new Chart(ctx.getContext('2d'), {
          type: 'line',
          data: {
            labels,
            datasets: [
              {
                label: data.bond1?.name || isin1,
                data: d1,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59,130,246,.08)',
                borderWidth: 2,
                fill: false,
                tension: 0.25,
                pointRadius: 0,
                pointHoverRadius: 4,
              },
              {
                label: data.bond2?.name || isin2,
                data: d2,
                borderColor: '#f59e0b',
                backgroundColor: 'rgba(245,158,11,.06)',
                borderWidth: 2,
                fill: false,
                tension: 0.25,
                pointRadius: 0,
                pointHoverRadius: 4,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)}`,
                },
              },
            },
            scales: {
              x: {
                ticks: { maxTicksLimit: 8, font: { size: 11 }, color: 'var(--text-tertiary)' },
                grid: { display: false },
              },
              y: {
                ticks: { font: { size: 11 }, color: 'var(--text-tertiary)', callback: v => v.toFixed(1) },
                grid: { color: 'rgba(var(--accent-rgb),.06)' },
              },
            },
          },
        });
      });
    })
    .catch(() => {
      if (loadEl)  loadEl.style.display = 'none';
      if (emptyEl) emptyEl.style.display = 'block';
      window.Common.showToast('Ошибка загрузки данных MOEX', true);
    });
}

function clearCompare() {
  ['compareIsin1', 'compareIsin2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  if (_compareChart) { _compareChart.destroy(); _compareChart = null; }
  const emptyEl = document.getElementById('compareEmpty');
  if (emptyEl) emptyEl.style.display = 'block';
  const legendEl = document.getElementById('compareLegend');
  if (legendEl) legendEl.style.display = 'none';
}

// ── Benchmark Chart ───────────────────────────────────────────────────────────

let _benchmarkChart = null;
let _benchmarkRange = 'month';
let _benchmarkLoaded = false;

function loadBenchmarkIfNeeded() {
  if (!_benchmarkLoaded) loadBenchmark(_benchmarkRange);
}

function setBenchmarkRange(range, btn) {
  _benchmarkRange = range;
  document.querySelectorAll('#benchmarkRangeBtns .btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  _benchmarkLoaded = false;
  loadBenchmark(range);
}

function _onChartJsReady(fn) {
  if (window.Chart) { fn(); return; }
  const script = document.querySelector('script[src*="chart.js"]');
  if (!script) { setTimeout(() => _onChartJsReady(fn), 100); return; }
  script.addEventListener('load', fn);
}

function loadBenchmark(range) {
  const loadEl  = document.getElementById('benchmark-loading');
  const emptyEl = document.getElementById('benchmarkEmpty');
  const statsEl = document.getElementById('benchmarkStats');
  if (loadEl)  loadEl.style.display = 'block';
  if (emptyEl) emptyEl.style.display = 'none';
  if (statsEl) statsEl.style.display = 'none';

  fetch(`/api/portfolio/benchmark?range=${range}`)
    .then(r => r.json())
    .then(data => {
      if (loadEl) loadEl.style.display = 'none';
      const rgbi = (data.rgbi || []).filter(d => d.close || d.value);
      if (!rgbi.length) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }
      const labels = rgbi.map(d => d.date || d.tradedate || '');
      const values = rgbi.map(d => parseFloat(d.close || d.value || 0));

      const first = values[0], last = values[values.length - 1];
      const chg = last - first;
      const chgPct = first ? (chg / first * 100) : 0;
      if (document.getElementById('benchmarkFirst')) document.getElementById('benchmarkFirst').textContent = first.toFixed(2);
      if (document.getElementById('benchmarkLast'))  document.getElementById('benchmarkLast').textContent = last.toFixed(2);
      const chgEl = document.getElementById('benchmarkChange');
      if (chgEl) {
        const sign = chg >= 0 ? '+' : '';
        chgEl.textContent = `${sign}${chg.toFixed(2)} (${sign}${chgPct.toFixed(2)}%)`;
        chgEl.style.color = chg >= 0 ? 'var(--emerald-500)' : '#ef4444';
      }
      if (statsEl) statsEl.style.display = 'flex';

      _onChartJsReady(() => {
        const ctx = document.getElementById('benchmarkChart');
        if (!ctx) return;
        if (_benchmarkChart) _benchmarkChart.destroy();
        const color = chg >= 0 ? '#10b981' : '#ef4444';
        _benchmarkChart = new Chart(ctx.getContext('2d'), {
          type: 'line',
          data: {
            labels,
            datasets: [{
              label: 'RGBI',
              data: values,
              borderColor: color,
              backgroundColor: color + '18',
              borderWidth: 2,
              fill: true,
              tension: 0.3,
              pointRadius: 0,
              pointHoverRadius: 4,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y.toFixed(2)}` } },
            },
            scales: {
              x: {
                ticks: { maxTicksLimit: 8, font: { size: 11 }, color: 'var(--text-tertiary)' },
                grid: { display: false },
              },
              y: {
                ticks: { font: { size: 11 }, color: 'var(--text-tertiary)' },
                grid: { color: 'rgba(var(--accent-rgb),.06)' },
              },
            },
          },
        });
        _benchmarkLoaded = true;
      });
    })
    .catch(() => {
      if (loadEl)  loadEl.style.display = 'none';
      if (emptyEl) emptyEl.style.display = 'block';
    });
}

// ── Tax Report ────────────────────────────────────────────────────────────────

let _taxLoaded = false;

function loadTaxIfNeeded() {
  if (!_taxLoaded) loadTax();
}

function loadTax() {
  const year = document.getElementById('taxYearSelect')?.value || new Date().getFullYear();
  const loadEl    = document.getElementById('tax-loading');
  const summaryEl = document.getElementById('taxSummary');
  const tableWrap = document.getElementById('taxTableWrap');
  const emptyEl   = document.getElementById('taxEmpty');

  if (loadEl)    loadEl.style.display = 'block';
  if (summaryEl) summaryEl.style.display = 'none';
  if (tableWrap) tableWrap.style.display = 'none';
  if (emptyEl)   emptyEl.style.display = 'none';

  fetch(`/api/portfolio/tax?year=${year}`)
    .then(r => r.json())
    .then(data => {
      if (loadEl) loadEl.style.display = 'none';
      const trades = data.trades || [];

      if (!trades.length) {
        if (emptyEl) emptyEl.style.display = 'block';
        return;
      }

      const _fmt = v => v != null ? v.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' ₽' : '—';
      const el = id => document.getElementById(id);
      if (el('taxGrossProfit')) el('taxGrossProfit').textContent = _fmt(data.gross_profit);
      if (el('taxTotalComm'))  el('taxTotalComm').textContent = _fmt(data.total_commission);
      if (el('taxBase'))       el('taxBase').textContent = _fmt(data.taxable_base);
      if (el('taxAmount'))     el('taxAmount').textContent = _fmt(data.tax_amount);
      if (summaryEl) summaryEl.style.display = 'grid';

      const tbody = document.getElementById('tax-table-body');
      if (tbody) {
        tbody.innerHTML = trades.map(t => {
          const pnlCls = t.pnl >= 0 ? 'text-success' : 'text-danger';
          return `<tr>
            <td data-label="Название">${t.name}</td>
            <td data-label="ISIN"><code style="font-size:.78rem">${t.isin}</code></td>
            <td data-label="Кол-во">${t.amount}</td>
            <td data-label="Цена покупки">${(t.buy_price || 0).toFixed(2)}</td>
            <td data-label="Цена продажи">${(t.sell_price || 0).toFixed(2)}</td>
            <td data-label="Комиссия">${(t.commission || 0).toFixed(2)}</td>
            <td data-label="P&L ₽" class="${pnlCls}">${t.pnl >= 0 ? '+' : ''}${(t.pnl || 0).toFixed(2)}</td>
            <td data-label="Дата продажи">${t.sell_date || '—'}</td>
          </tr>`;
        }).join('');
      }
      if (tableWrap) tableWrap.style.display = 'block';
      _taxLoaded = true;
    })
    .catch(() => {
      if (loadEl)  loadEl.style.display = 'none';
      if (emptyEl) emptyEl.style.display = 'block';
    });
}

// Reset taxLoaded when year changes
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('taxYearSelect')?.addEventListener('change', () => { _taxLoaded = false; });
});
