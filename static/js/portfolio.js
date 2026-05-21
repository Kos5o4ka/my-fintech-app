// ── State ─────────────────────────────────────────────────────────────────────
let myChartInstance = null;
let marketChartInstance = null;
let chartModal = null;
let currentBondIsin = null;
let currentBondLabels = [];
let currentBondPrices = [];
let currentBondNkd = [];
let currentBondYtm = [];
let historyLoaded = false;

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
    await fetchChartAnalytics();
    await fetchCouponCalendar();
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

// ── Active portfolio ──────────────────────────────────────────────────────────
async function fetchActivePortfolio() {
    const tbody = document.getElementById('bonds-table-body');
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4">
        <div class="spinner-border text-primary" role="status">
            <span class="visually-hidden">Загрузка…</span>
        </div>
    </td></tr>`;

    const response = await fetch('/api/portfolio');
    if (response.status === 401) { window.location.href = '/'; return; }
    const data = await response.json();

    document.getElementById('total-portfolio-value').innerText =
        data.total_value.toLocaleString('ru-RU', { minimumFractionDigits: 2 });

    bondsData = data.bonds || [];
    renderBondRows();
}

function renderBondRows() {
    const tbody = document.getElementById('bonds-table-body');
    tbody.innerHTML = '';

    if (!bondsData.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">
            Инвестиционный портфель пуст.<br>
            <small class="text-secondary">Добавьте первую облигацию с помощью формы слева.</small>
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

// ── Trade history (FEAT-3) ────────────────────────────────────────────────────
function loadHistoryIfNeeded() {
    if (!historyLoaded) {
        fetchTradeHistory();
        historyLoaded = true;
    }
}

async function fetchTradeHistory() {
    const loading = document.getElementById('history-loading');
    const tbody = document.getElementById('history-table-body');
    if (loading) loading.style.display = 'block';

    try {
        const response = await fetch('/api/portfolio/history');
        if (!response.ok) return;
        const data = await response.json();
        tbody.innerHTML = '';

        if (!data.trades || data.trades.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">
                История сделок пуста.</td></tr>`;
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
            window.Common.showToast(data.message);
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

// ── Sell bond ─────────────────────────────────────────────────────────────────
function sellTrigger(bondId, name, sellPrice) {
    window.Common.askConfirmation(
        `Вы действительно хотите зафиксировать продажу облигации ${name} и перевести её в архив сделок?`,
        async () => {
            const response = await window.Common.csrfFetch(`/api/sell_bond/${bondId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sell_price: sellPrice })
            });
            const data = await response.json();
            if (response.ok) {
                window.Common.showToast(data.message);
                historyLoaded = false;
                await loadDashboard();
            } else {
                window.Common.showSystemMessage(data.message, true);
            }
        }
    );
}

// ── Logout ────────────────────────────────────────────────────────────────────
async function handleLogout() {
    await window.Common.csrfFetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/';
}

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
})();

// ── Bootstrap ─────────────────────────────────────────────────────────────────
loadDashboard();
