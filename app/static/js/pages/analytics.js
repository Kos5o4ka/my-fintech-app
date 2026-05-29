// ── State ─────────────────────────────────────────────────────────────────────
let myChartInstance = null;
let allocationChartInstance = null;
let compareChartInstance = null;
let benchmarkChartInstance = null;
let benchmarkRange = 'month';
let benchmarkLoaded = false;
let taxLoaded = false;
let bondsData = [];

// Helper to check if Chart is loaded
function onChartJsReady(fn) {
    if (window.Chart) { fn(); return; }
    const script = document.querySelector('script[src*="chart.js"]');
    if (!script) { setTimeout(() => onChartJsReady(fn), 100); return; }
    script.addEventListener('load', fn);
}

// ── Dashboard / Stats ────────────────────────────────────────────────────────
async function fetchActivePortfolio() {
    const response = await fetch('/api/portfolio');
    if (response.status === 401) { window.location.href = '/'; return; }
    const data = await response.json();

    const valEl = document.getElementById('total-portfolio-value');
    if (valEl) valEl.innerText = data.total_value.toLocaleString('ru-RU', { minimumFractionDigits: 2 });

    bondsData = data.bonds || [];
    renderAllocationChart();
}

let allocationChartExpanded = false;
function renderAllocationChart() {
    const canvas = document.getElementById('allocationChart');
    const emptyEl = document.getElementById('allocationEmpty');
    if (!canvas) return;

    if (!bondsData.length) {
        if (emptyEl) emptyEl.style.display = 'block';
        if (allocationChartInstance) { allocationChartInstance.destroy(); allocationChartInstance = null; }
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    let displayData = [...bondsData].sort((a, b) => b.current_value - a.current_value);
    
    if (!allocationChartExpanded && displayData.length > 10) {
        const top10 = displayData.slice(0, 10);
        const others = displayData.slice(10);
        const otherValue = others.reduce((sum, b) => sum + b.current_value, 0);
        displayData = [...top10, { name: 'Другое', current_value: otherValue, isOther: true }];
    }

    const labels = displayData.map(b => b.name);
    const values = displayData.map(b => b.current_value);
    const colors = displayData.map((_, i) => {
        if (displayData[i].isOther) return '#94a3b8'; // gray color for other
        return `hsl(${Math.round((i * 137.5) % 360)}, 60%, 55%)`;
    });

    if (allocationChartInstance) allocationChartInstance.destroy();
    allocationChartInstance = new Chart(canvas.getContext('2d'), {
        type: 'doughnut',
        data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2 }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            onClick: (e, elements) => {
                if (!elements.length) return;
                const idx = elements[0].index;
                if (!allocationChartExpanded && displayData[idx].isOther) {
                    allocationChartExpanded = true;
                    renderAllocationChart();
                }
            },
            plugins: {
                legend: { position: 'right', labels: { font: { size: 10 }, boxWidth: 12 } },
                tooltip: {
                    callbacks: {
                        label: ctx => {
                            const total = ctx.dataset.data.reduce((s, v) => s + v, 0);
                            const pct = total ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                            return ` ${ctx.parsed.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽ (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

async function fetchChartAnalytics() {
    const response = await fetch('/api/portfolio_stats');
    if (!response.ok) return;
    const chartData = await response.json();
    const ctx = document.getElementById('profitChart');
    if (!ctx) return;
    if (myChartInstance) myChartInstance.destroy();
    myChartInstance = new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: chartData,
        options: { responsive: true, maintainAspectRatio: false }
    });
}

// ── Sharpe Ratio ──────────────────────────────────────────────────────────────
async function fetchSharpeRatio() {
    try {
        const r = await fetch('/api/portfolio/sharpe');
        if (!r.ok) return;
        const data = await r.json();
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
    } catch (_) {}
}

// ── Tax Report ────────────────────────────────────────────────────────────────
function loadTaxIfNeeded() {
    if (!taxLoaded) loadTax();
}

async function loadTax() {
    const yearSelect = document.getElementById('taxYearSelect');
    const year = yearSelect ? yearSelect.value : new Date().getFullYear();
    const loadEl    = document.getElementById('tax-loading');
    const summaryEl = document.getElementById('taxSummary');
    const tableWrap = document.getElementById('taxTableWrap');
    const emptyEl   = document.getElementById('taxEmpty');

    if (loadEl)    loadEl.style.display = 'block';
    if (summaryEl) summaryEl.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'none';
    if (emptyEl)   emptyEl.style.display = 'none';

    try {
        const r = await fetch(`/api/portfolio/tax?year=${year}`);
        if (!r.ok) return;
        const data = await r.json();
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
            const esc = window.Common.escapeHtml;
            tbody.innerHTML = trades.map(t => {
                const pnlCls = t.pnl >= 0 ? 'text-success' : 'text-danger';
                let rowHtml = `<tr>
                    <td data-label="Название">${esc(t.name)}</td>
                    <td data-label="ISIN"><code style="font-size:.78rem">${esc(t.isin)}</code></td>
                    <td data-label="Кол-во">${t.amount}</td>
                    <td data-label="Цена покупки">${(t.buy_price || 0).toFixed(2)}</td>
                    <td data-label="Цена продажи">${t.sell_price != null ? t.sell_price.toFixed(2) : '—'}</td>
                    <td data-label="Комиссия">${(t.commission || 0).toFixed(2)}</td>
                    <td data-label="Купоны">${(t.coupons || 0).toFixed(2)}</td>
                    <td data-label="P&L ₽" class="${pnlCls}">${t.pnl >= 0 ? '+' : ''}${(t.pnl || 0).toFixed(2)}</td>
                    <td data-label="Дата продажи">${esc(t.sell_date || '—')}
                    ${t.sub_trades ? `<button class="btn btn-sm btn-link p-0 ms-1" onclick="toggleSubTrades('sub-${t.id}')">▾</button>` : ''}
                    </td>
                </tr>`;
                
                if (t.sub_trades) {
                    const subRows = t.sub_trades.map(st => {
                        const subPnlCls = st.pnl >= 0 ? 'text-success' : 'text-danger';
                        return `<tr>
                            <td colspan="2"></td>
                            <td class="text-muted small">${st.amount} шт.</td>
                            <td colspan="2"></td>
                            <td class="text-muted small">${(st.commission || 0).toFixed(2)} ₽</td>
                            <td></td>
                            <td class="${subPnlCls} small">${st.pnl >= 0 ? '+' : ''}${(st.pnl || 0).toFixed(2)} ₽</td>
                            <td class="text-muted small">${esc(st.time || '')}</td>
                        </tr>`;
                    }).join('');
                    rowHtml += `<tr id="sub-${t.id}" style="display:none;background:var(--surface-0)"><td colspan="9" style="padding:0"><table class="table table-sm table-borderless mb-0" style="font-size:0.85rem"><tbody>${subRows}</tbody></table></td></tr>`;
                }
                return rowHtml;
            }).join('');
        }
        if (tableWrap) tableWrap.style.display = 'block';
        taxLoaded = true;
    } catch (_) {
        if (loadEl)  loadEl.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'block';
    }
}

function toggleSubTrades(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = el.style.display === 'none' ? 'table-row' : 'none';
}

// ── Compare two bonds ─────────────────────────────────────────────────────────
async function runCompare() {
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

    try {
        const r = await fetch(`/api/portfolio/compare?isin1=${isin1}&isin2=${isin2}&range=${range}`);
        const data = await r.json();
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

        onChartJsReady(() => {
            const ctx = document.getElementById('compareChart');
            if (!ctx) return;
            if (compareChartInstance) compareChartInstance.destroy();
            compareChartInstance = new Chart(ctx.getContext('2d'), {
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
    } catch (_) {
        if (loadEl)  loadEl.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'block';
        window.Common.showToast('Ошибка загрузки данных MOEX', true);
    }
}

function clearCompare() {
    ['compareIsin1', 'compareIsin2'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    if (compareChartInstance) { compareChartInstance.destroy(); compareChartInstance = null; }
    const emptyEl = document.getElementById('compareEmpty');
    if (emptyEl) emptyEl.style.display = 'block';
    const legendEl = document.getElementById('compareLegend');
    if (legendEl) legendEl.style.display = 'none';
}

// ── Benchmark Chart ───────────────────────────────────────────────────────────
function loadBenchmarkIfNeeded() {
    if (!benchmarkLoaded) loadBenchmark(benchmarkRange);
}

function setBenchmarkRange(range, btn) {
    benchmarkRange = range;
    document.querySelectorAll('#benchmarkRangeBtns button').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    benchmarkLoaded = false;
    loadBenchmark(range);
}

async function loadBenchmark(range) {
    const loadEl  = document.getElementById('benchmark-loading');
    const emptyEl = document.getElementById('benchmarkEmpty');
    const statsEl = document.getElementById('benchmarkStats');
    if (loadEl)  loadEl.style.display = 'block';
    if (emptyEl) emptyEl.style.display = 'none';
    if (statsEl) statsEl.style.display = 'none';

    try {
        const r = await fetch(`/api/portfolio/benchmark?range=${range}`);
        const data = await r.json();
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

        onChartJsReady(() => {
            const ctx = document.getElementById('benchmarkChart');
            if (!ctx) return;
            if (benchmarkChartInstance) benchmarkChartInstance.destroy();
            const color = chg >= 0 ? '#10b981' : '#ef4444';
            benchmarkChartInstance = new Chart(ctx.getContext('2d'), {
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
            benchmarkLoaded = true;
        });
    } catch (_) {
        if (loadEl)  loadEl.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'block';
    }
}

// ── Setup listeners on load ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Initial fetch
    fetchActivePortfolio();
    fetchChartAnalytics();
    fetchSharpeRatio();
    loadTax();

    // Tax year change listener
    document.getElementById('taxYearSelect')?.addEventListener('change', () => {
        taxLoaded = false;
        loadTax();
    });

    // Compare handlers
    document.getElementById('compareRunBtn')?.addEventListener('click', runCompare);
    document.getElementById('compareClearBtn')?.addEventListener('click', clearCompare);

    // Benchmark buttons
    document.querySelectorAll('#benchmarkRangeBtns button').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const range = e.target.dataset.range || 'month';
            setBenchmarkRange(range, e.target);
        });
    });

    // Tab switcher activation checks
    document.getElementById('tax-tab')?.addEventListener('click', loadTaxIfNeeded);
    document.getElementById('benchmark-tab')?.addEventListener('click', loadBenchmarkIfNeeded);
});
