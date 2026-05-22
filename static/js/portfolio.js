// ── State ─────────────────────────────────────────────────────────────────────
let myChartInstance = null;
let allocationChartInstance = null;
let marketChartInstance = null;
let chartModal = null;
let sellModal = null;
let currentBondIsin = null;
let currentBondLabels = [];
let currentBondPrices = [];
let currentBondNkd = [];
let currentBondYtm = [];
let historyLoaded = false;
let incomeData = {};

// Table sort state
let bondsData = [];
let sortKey = null;
let sortDir = 1; // 1 = ascending, -1 = descending

// Set today's date as default
document.getElementById('bondDate').value = new Date().toISOString().split('T')[0];

// Init Bootstrap tooltips
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
        new bootstrap.Tooltip(el);
    });
});

// ── Bond chart ────────────────────────────────────────────────────────────────
async function openBondChart(isin) {
    currentBondIsin = isin;
    document.getElementById('chartModalIsinTitle').innerText = isin;
    if (!chartModal) chartModal = new bootstrap.Modal(document.getElementById('bondChartModal'));
    chartModal.show();

    await loadBondChartData('month');
    const buttons = document.querySelectorAll('#periodBtnGroup .btn');
    buttons.forEach(btn => btn.classList.remove('active'));
    const defaultBtn = document.querySelector('#periodBtnGroup [data-period="month"]');
    if (defaultBtn) defaultBtn.classList.add('active');
}

async function loadBondChartData(period) {
    if (!currentBondIsin) return;

    const response = await fetch(`/api/bond_chart/${currentBondIsin}?range=${period}`);
    if (!response.ok) return;

    const resData = await response.json();
    currentBondLabels = resData.labels || [];
    currentBondPrices = resData.data || [];
    currentBondNkd = resData.nkd || [];
    currentBondYtm = resData.ytm || [];

    const ctx = document.getElementById('marketBondChart').getContext('2d');
    if (marketChartInstance) marketChartInstance.destroy();

    marketChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: currentBondLabels,
            datasets: [{
                label: 'Рыночная стоимость (₽)',
                data: currentBondPrices,
                borderColor: '#0d6efd',
                backgroundColor: 'rgba(13, 110, 253, 0.04)',
                borderWidth: 2,
                fill: true,
                pointRadius: period === 'all' ? 0 : (period === 'day' || period === 'week' ? 5 : 2)
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: ctx => `Цена бумаги: ${ctx.parsed.y} ₽`,
                        footer: items => {
                            const i = items[0].dataIndex;
                            return `НКД на дату: ${currentBondNkd[i]} ₽\nДоходность YTM: ${currentBondYtm[i]} %`;
                        }
                    }
                },
                zoom: {
                    pan: { enabled: true, mode: 'x' },
                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' }
                }
            }
        }
    });
}

function applyChartScale(period, ev) {
    if (ev && ev.target && ev.target.classList.contains('btn')) {
        document.querySelectorAll('#periodBtnGroup .btn').forEach(b => b.classList.remove('active'));
        ev.target.classList.add('active');
    }
    loadBondChartData(period);
}

// ── Dashboard loader ──────────────────────────────────────────────────────────
async function loadDashboard() {
    await fetchActivePortfolio();
    fetchChartAnalytics();
    fetchCouponCalendar();
    fetchIncomeWidget();
}

// ── Coupon calendar ───────────────────────────────────────────────────────────
async function fetchCouponCalendar() {
    const response = await fetch('/api/portfolio/calendar');
    if (!response.ok) return;
    const events = await response.json();
    const list = document.getElementById('coupon-calendar-list');
    list.innerHTML = '';
    if (events.length === 0) {
        list.innerHTML = '<li class="list-group-item text-center text-muted py-3">Нет предстоящих купонов.</li>';
        return;
    }
    const esc = window.Common.escapeHtml;
    events.forEach(e => {
        list.innerHTML += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <div><b>${esc(e.name)}</b><br><small class="text-muted">${esc(e.date)}</small></div>
                <span class="badge bg-success font-monospace">+ ${parseFloat(e.total_payout).toFixed(2)} ₽</span>
            </li>`;
    });
}

// ── Table sort ────────────────────────────────────────────────────────────────
function sortTable(key) {
    if (sortKey === key) sortDir = -sortDir;
    else { sortKey = key; sortDir = 1; }
    renderBondRows();
    _updateSortIndicators();
}

function _updateSortIndicators() {
    document.querySelectorAll('.sort-icon').forEach(el => {
        const col = el.dataset.col;
        el.textContent = col === sortKey ? (sortDir === 1 ? ' ↑' : ' ↓') : '';
    });
}

// ── Skeleton rows ─────────────────────────────────────────────────────────────
function _skeletonRows(cols = 8, rows = 4) {
    let html = '';
    const widths = ['60%', '30%', '20%', '25%', '20%', '20%', '30%', '15%'];
    for (let r = 0; r < rows; r++) {
        html += '<tr>';
        for (let c = 0; c < cols; c++) {
            const w = widths[c] || '30%';
            html += `<td><span class="skeleton-cell" style="width:${w}"></span></td>`;
        }
        html += '</tr>';
    }
    return html;
}

// ── Active portfolio ──────────────────────────────────────────────────────────
async function fetchActivePortfolio() {
    const tbody = document.getElementById('bonds-table-body');
    tbody.innerHTML = _skeletonRows();

    const response = await fetch('/api/portfolio');
    if (response.status === 401) { window.location.href = '/'; return; }
    const data = await response.json();

    document.getElementById('total-portfolio-value').innerText =
        data.total_value.toLocaleString('ru-RU', { minimumFractionDigits: 2 });

    const ytmEl = document.getElementById('portfolio-ytm');
    if (ytmEl) ytmEl.textContent = data.portfolio_ytm ? data.portfolio_ytm.toFixed(2) + ' %' : '—';

    const countEl = document.getElementById('portfolio-count');
    if (countEl) countEl.textContent = (data.bonds || []).length;

    bondsData = data.bonds || [];
    renderBondRows();
    renderAllocationChart();
}

function renderBondRows() {
    const tbody = document.getElementById('bonds-table-body');
    tbody.innerHTML = '';

    if (!bondsData.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-5">
            <div style="font-size:2.5rem;opacity:.2;line-height:1">📊</div>
            <div class="fw-semibold mt-2 mb-1">Портфель пуст</div>
            <small class="text-secondary">Найдите облигацию по ISIN или названию и добавьте первую позицию.</small>
        </td></tr>`;
        return;
    }

    // Apply sort
    let sorted = [...bondsData];
    if (sortKey) {
        sorted.sort((a, b) => {
            let va = a[sortKey], vb = b[sortKey];
            if (typeof va === 'string') { va = va.toLowerCase(); vb = (vb || '').toLowerCase(); }
            return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
        });
    }

    const esc = window.Common.escapeHtml;
    sorted.forEach(bond => {
        const pnl = bond.pnl ?? 0;
        const pnlPct = bond.pnl_pct ?? 0;
        const pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
        const sign = pnl >= 0 ? '+' : '';

        tbody.innerHTML += `
            <tr>
                <td><b>${esc(bond.name)}</b></td>
                <td><b class="isin-link" onclick="openBondChart(this.dataset.isin)"
                        data-isin="${esc(bond.isin)}">${esc(bond.isin)}</b></td>
                <td>${bond.amount} шт.</td>
                <td>${bond.buy_price.toFixed(2)} ₽</td>
                <td class="text-primary"><b>${(bond.nkd || 0).toFixed(2)} ₽</b></td>
                <td class="text-info"><b>${(bond.ytm || 0).toFixed(2)} %</b></td>
                <td class="${pnlClass}" title="Нереализованная прибыль/убыток">
                    <b>${sign}${pnl.toFixed(2)} ₽</b><br>
                    <small>${sign}${pnlPct.toFixed(2)}%</small>
                </td>
                <td><button
                    onclick="sellTrigger(parseInt(this.dataset.id), this.dataset.name, parseFloat(this.dataset.price))"
                    data-id="${bond.id}"
                    data-name="${esc(bond.name)}"
                    data-price="${bond.last_price || bond.buy_price}"
                    class="btn btn-sm btn-outline-success">Продать</button></td>
            </tr>`;
    });
}

// ── Trade history ─────────────────────────────────────────────────────────────
function loadHistoryIfNeeded() {
    if (!historyLoaded) {
        fetchTradeHistory();
        historyLoaded = true;
    }
}

async function fetchTradeHistory(dateFrom = '', dateTo = '') {
    const loading = document.getElementById('history-loading');
    const tbody = document.getElementById('history-table-body');
    if (loading) loading.style.display = 'block';
    tbody.innerHTML = _skeletonRows(8, 3);

    try {
        const params = new URLSearchParams();
        if (dateFrom) params.set('date_from', dateFrom);
        if (dateTo) params.set('date_to', dateTo);
        const url = '/api/portfolio/history' + (params.toString() ? '?' + params.toString() : '');
        const response = await fetch(url);
        if (!response.ok) return;
        const data = await response.json();
        tbody.innerHTML = '';

        if (!data.trades || data.trades.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">
                ${dateFrom || dateTo ? 'Нет сделок за выбранный период.' : 'История сделок пуста.'}
            </td></tr>`;
            return;
        }

        const esc = window.Common.escapeHtml;
        data.trades.forEach(t => {
            const pnlClass = t.pnl >= 0 ? 'text-success' : 'text-danger';
            const sign = t.pnl >= 0 ? '+' : '';
            tbody.innerHTML += `
                <tr>
                    <td><b>${esc(t.name)}</b></td>
                    <td><small class="text-muted">${esc(t.isin)}</small></td>
                    <td>${t.amount} шт.</td>
                    <td>${t.buy_price.toFixed(2)} ₽</td>
                    <td>${t.sell_price.toFixed(2)} ₽</td>
                    <td class="${pnlClass}"><b>${sign}${t.pnl.toFixed(2)} ₽</b></td>
                    <td class="${pnlClass}"><b>${sign}${t.pnl_pct.toFixed(2)}%</b></td>
                    <td><small>${esc(t.sell_date || '—')}</small></td>
                </tr>`;
        });
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function applyHistoryFilter() {
    const from = document.getElementById('historyDateFrom').value;
    const to = document.getElementById('historyDateTo').value;
    fetchTradeHistory(from, to);
}

function clearHistoryFilter() {
    document.getElementById('historyDateFrom').value = '';
    document.getElementById('historyDateTo').value = '';
    fetchTradeHistory();
}

// ── Bond preview ──────────────────────────────────────────────────────────────
async function fetchBondPreview(isin) {
    if (!isin || isin.length < 2) return;
    try {
        const res = await fetch(`/api/bond_preview/${encodeURIComponent(isin)}`);
        if (!res.ok) { hideBondPreview(); return; }
        const d = await res.json();
        if (d.status !== 'ok') { hideBondPreview(); return; }

        document.getElementById('previewName').textContent = d.name || isin;
        document.getElementById('previewPrice').textContent = d.price != null ? d.price.toFixed(2) + ' ₽' : '—';
        document.getElementById('previewYtm').textContent = d.ytm != null ? d.ytm.toFixed(2) + ' %' : '—';
        document.getElementById('previewMatdate').textContent = d.matdate || '—';
        document.getElementById('previewNkd').textContent = d.nkd != null ? d.nkd.toFixed(2) + ' ₽' : '—';

        let couponText = '—';
        if (d.coupon_pct != null) {
            couponText = d.coupon_pct + '%';
            if (d.coupon_freq) couponText += ` × ${d.coupon_freq}/год`;
        }
        document.getElementById('previewCoupon').textContent = couponText;

        document.getElementById('bondPreview').style.display = 'block';

        // Auto-fill buy price if the field is empty or previously auto-filled
        const priceField = document.getElementById('bondBuyPrice');
        if (d.price != null && (!priceField.value || priceField.dataset.autofilled === 'true')) {
            priceField.value = d.price.toFixed(2);
            priceField.dataset.autofilled = 'true';
        }
    } catch (_) {
        hideBondPreview();
    }
}

function hideBondPreview() {
    document.getElementById('bondPreview').style.display = 'none';
}

// ── Add bond form ─────────────────────────────────────────────────────────────
document.getElementById('addBondForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('addBondBtn');
    btn.disabled = true;
    btn.textContent = 'Загрузка…';

    const isin = document.getElementById('bondIsin').value.trim();
    const amount = document.getElementById('bondAmount').value;
    const buy_price = document.getElementById('bondBuyPrice').value;
    const purchase_date = document.getElementById('bondDate').value;

    try {
        const response = await window.Common.csrfFetch('/api/add_bond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ isin, amount, buy_price, purchase_date })
        });
        const data = await response.json();

        if (response.ok && data.status === 'success') {
            if (data.duplicate_warning) {
                window.Common.showToast(
                    `${data.message} Внимание: в портфеле уже есть ${data.existing_amount} шт. этой бумаги.`,
                    false, true
                );
            } else {
                window.Common.showToast(data.message);
            }
            document.getElementById('addBondForm').reset();
            document.getElementById('bondDate').value = new Date().toISOString().split('T')[0];
            historyLoaded = false;
            await loadDashboard();
        } else {
            window.Common.showSystemMessage(data.message, true);
        }
    } finally {
        btn.disabled = false;
        btn.textContent = 'Добавить в портфель';
    }
});


// ── Profit chart ──────────────────────────────────────────────────────────────
async function fetchChartAnalytics() {
    const response = await fetch('/api/portfolio_stats');
    if (!response.ok) return;
    const chartData = await response.json();
    const ctx = document.getElementById('profitChart').getContext('2d');
    if (myChartInstance) myChartInstance.destroy();
    myChartInstance = new Chart(ctx, {
        type: 'bar',
        data: chartData,
        options: { responsive: true, maintainAspectRatio: false }
    });
}

// ── Bond search autocomplete (FEAT-4) ─────────────────────────────────────────
(function setupBondSearch() {
    const isinInput = document.getElementById('bondIsin');
    const dropdown = document.getElementById('isinDropdown');
    let debounceTimer = null;

    isinInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const q = isinInput.value.trim();
        if (q.length < 2) { dropdown.style.display = 'none'; return; }
        debounceTimer = setTimeout(async () => {
            try {
                const res = await fetch(`/api/search_bond?q=${encodeURIComponent(q)}`);
                if (!res.ok) return;
                renderDropdown(await res.json());
            } catch (_) {}
        }, 300);
    });

    function renderDropdown(results) {
        dropdown.innerHTML = '';
        if (!results || !results.length) { dropdown.style.display = 'none'; return; }
        const esc = window.Common.escapeHtml;
        results.forEach(item => {
            const div = document.createElement('div');
            div.className = 'isin-dropdown-item';
            div.innerHTML = `<span class="fw-semibold">${esc(item.isin)}</span>
                             <span class="text-muted ms-2 small">${esc(item.name)}</span>`;
            div.addEventListener('mousedown', e => {
                e.preventDefault();
                isinInput.value = item.isin;
                dropdown.style.display = 'none';
                fetchBondPreview(item.isin);
            });
            dropdown.appendChild(div);
        });
        dropdown.style.display = 'block';
    }

    document.addEventListener('click', e => {
        if (!isinInput.contains(e.target) && !dropdown.contains(e.target))
            dropdown.style.display = 'none';
    });

    isinInput.addEventListener('keydown', e => {
        if (e.key === 'Escape') dropdown.style.display = 'none';
    });

    isinInput.addEventListener('blur', () => {
        const val = isinInput.value.trim();
        if (val.length >= 10) fetchBondPreview(val);
    });

    isinInput.addEventListener('input', () => {
        if (!isinInput.value.trim()) hideBondPreview();
        document.getElementById('bondBuyPrice').dataset.autofilled = '';
    });
})();

// ── Allocation pie chart ──────────────────────────────────────────────────────
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

    const labels = bondsData.map(b => b.name);
    const values = bondsData.map(b => b.current_value);
    const colors = bondsData.map((_, i) => `hsl(${Math.round((i * 137.5) % 360)}, 60%, 55%)`);

    if (allocationChartInstance) allocationChartInstance.destroy();
    allocationChartInstance = new Chart(canvas.getContext('2d'), {
        type: 'doughnut',
        data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 2 }] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
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

// ── Coupon income widget ──────────────────────────────────────────────────────
async function fetchIncomeWidget() {
    try {
        const res = await fetch('/api/portfolio/income');
        if (!res.ok) return;
        incomeData = await res.json();
        showIncome('30d');
    } catch (_) {}
}

function showIncome(period, btn) {
    if (btn) {
        document.querySelectorAll('#incomeGroup .btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    }
    const val = incomeData[period];
    const el = document.getElementById('incomeValue');
    const hint = document.getElementById('incomeHint');
    if (el) el.textContent = val != null
        ? val.toLocaleString('ru-RU', { minimumFractionDigits: 2 }) + ' ₽'
        : '—';
    const labels = { '30d': 'следующие 30 дней', '90d': 'следующие 90 дней', '365d': 'следующий год' };
    if (hint) hint.textContent = 'купоны за ' + (labels[period] || period);
}

// ── Sell modal ────────────────────────────────────────────────────────────────
function sellTrigger(bondId, name, sellPrice) {
    const nameEl = document.getElementById('sellModalBondName');
    const priceEl = document.getElementById('sellPriceInput');
    const commEl  = document.getElementById('sellCommissionInput');
    if (nameEl) nameEl.textContent = name;
    if (priceEl) priceEl.value = sellPrice.toFixed(2);
    if (commEl)  commEl.value = '';

    if (!sellModal) sellModal = new bootstrap.Modal(document.getElementById('sellModal'));

    const btn = document.getElementById('sellModalConfirmBtn');
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);

    newBtn.addEventListener('click', async () => {
        const price = parseFloat(document.getElementById('sellPriceInput').value);
        const comm  = parseFloat(document.getElementById('sellCommissionInput').value) || 0;
        if (isNaN(price) || price <= 0) return;

        sellModal.hide();
        const response = await window.Common.csrfFetch(`/api/sell_bond/${bondId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sell_price: price, broker_commission: comm || null })
        });
        const data = await response.json();
        if (response.ok) {
            window.Common.showToast(data.message);
            historyLoaded = false;
            await loadDashboard();
        } else {
            window.Common.showSystemMessage(data.message, true);
        }
    });

    sellModal.show();
}

// ── Watchlist ─────────────────────────────────────────────────────────────────
let watchlistLoaded = false;

function loadWatchlistIfNeeded() {
    if (!watchlistLoaded) fetchWatchlist();
}

async function fetchWatchlist() {
    const tbody = document.getElementById('watchlist-table-body');
    tbody.innerHTML = _skeletonRows(7, 3);
    const res = await window.Common.csrfFetch('/api/watchlist');
    if (!res.ok) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-3">Ошибка загрузки</td></tr>';
        return;
    }
    const items = await res.json();
    watchlistLoaded = true;
    const esc = window.Common.escapeHtml;
    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">
            ⭐ Список пуст. Добавьте облигации через кнопку «+ Добавить».
        </td></tr>`;
        return;
    }
    tbody.innerHTML = items.map(item => {
        const price = item.price != null ? item.price.toFixed(2) + ' ₽' : '—';
        const ytm   = item.ytm  != null ? item.ytm.toFixed(2)  + ' %' : '—';
        const nkd   = item.nkd  != null ? item.nkd.toFixed(2)  + ' ₽' : '—';
        return `<tr>
            <td>${esc(item.name)}</td>
            <td><span class="isin-link" onclick="openBondChart('${esc(item.isin)}')">${esc(item.isin)}</span></td>
            <td>${price}</td>
            <td>${ytm}</td>
            <td>${nkd}</td>
            <td class="text-muted small">${esc(item.added_at)}</td>
            <td>
                <button class="btn btn-sm btn-outline-danger" onclick="removeFromWatchlist('${esc(item.isin)}')">✕</button>
            </td>
        </tr>`;
    }).join('');
}

async function promptAddWatchlist() {
    const isin = prompt('Введите ISIN облигации:');
    if (!isin) return;
    const res = await window.Common.csrfFetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isin: isin.trim().toUpperCase() }),
    });
    const data = await res.json();
    if (res.ok) {
        window.Common.showToast(data.message);
        watchlistLoaded = false;
        fetchWatchlist();
    } else {
        window.Common.showSystemMessage(data.message, true);
    }
}

async function removeFromWatchlist(isin) {
    window.Common.askConfirmation(`Удалить ${isin} из избранного?`, async () => {
        const res = await window.Common.csrfFetch(`/api/watchlist/${isin}`, { method: 'DELETE' });
        const data = await res.json();
        window.Common.showToast(data.message, !res.ok);
        watchlistLoaded = false;
        fetchWatchlist();
    });
}

// ── Screener ──────────────────────────────────────────────────────────────────
async function runScreener() {
    const tbody = document.getElementById('screener-table-body');
    const loading = document.getElementById('screener-loading');
    loading.style.display = 'block';
    tbody.innerHTML = '';

    const params = new URLSearchParams();
    const minYtm = document.getElementById('screenerMinYtm').value;
    const maxYtm = document.getElementById('screenerMaxYtm').value;
    const matFrom = document.getElementById('screenerMatFrom').value;
    const matTo   = document.getElementById('screenerMatTo').value;
    if (minYtm) params.set('min_ytm', minYtm);
    if (maxYtm) params.set('max_ytm', maxYtm);
    if (matFrom) params.set('maturity_from', matFrom);
    if (matTo)   params.set('maturity_to', matTo);

    const res = await window.Common.csrfFetch('/api/screener?' + params.toString());
    loading.style.display = 'none';
    if (!res.ok) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-danger text-center py-3">Ошибка загрузки</td></tr>';
        return;
    }
    const results = await res.json();
    const esc = window.Common.escapeHtml;
    if (!results.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">Ничего не найдено по заданным фильтрам.</td></tr>';
        return;
    }
    tbody.innerHTML = results.map(b => {
        const ytm    = b.ytm    != null ? b.ytm.toFixed(2) + ' %' : '—';
        const coupon = b.coupon != null ? b.coupon + ' ₽' : '—';
        const mat    = b.matdate || '—';
        return `<tr>
            <td>${esc(b.name || b.secid)}</td>
            <td><span class="isin-link" onclick="openBondChart('${esc(b.isin)}')">${esc(b.isin)}</span></td>
            <td>${ytm}</td>
            <td>${esc(mat)}</td>
            <td>${coupon}</td>
            <td>
                <button class="btn btn-sm btn-outline-success" title="Добавить в избранное"
                    onclick="addScreenerToWatchlist('${esc(b.isin)}')">⭐</button>
            </td>
        </tr>`;
    }).join('');
}

function clearScreener() {
    ['screenerMinYtm','screenerMaxYtm','screenerMatFrom','screenerMatTo'].forEach(id => {
        document.getElementById(id).value = '';
    });
    const tbody = document.getElementById('screener-table-body');
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">Задайте фильтры и нажмите «Найти».</td></tr>';
}

async function addScreenerToWatchlist(isin) {
    const res = await window.Common.csrfFetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isin }),
    });
    const data = await res.json();
    window.Common.showToast(data.message, !res.ok && res.status !== 409);
    if (res.ok) { watchlistLoaded = false; }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
loadDashboard();
