let myChartInstance = null;
let marketChartInstance = null;
let infoModal = null;
let confirmModal = null;
let chartModal = null;
let currentBondIsin = null;
let currentBondLabels = [];
let currentBondPrices = [];
let currentBondNkd = [];
let currentBondYtm = [];

document.getElementById('bondDate').value = new Date().toISOString().split('T')[0];

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
                        label: function(context) {
                            return `Цена бумаги: ${context.parsed.y} ₽`;
                        },
                        footer: function(tooltipItems) {
                            const dataIndex = tooltipItems[0].dataIndex;
                            return `НКД на дату: ${currentBondNkd[dataIndex]} ₽\nДоходность YTM: ${currentBondYtm[dataIndex]} %`;
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
        const buttons = document.querySelectorAll('#periodBtnGroup .btn');
        buttons.forEach(btn => btn.classList.remove('active'));
        ev.target.classList.add('active');
    }

    loadBondChartData(period);
}

async function loadDashboard() {
    await fetchActivePortfolio();
    await fetchChartAnalytics();
    await fetchCouponCalendar();
}

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

async function fetchActivePortfolio() {
    const response = await fetch('/api/portfolio');
    if (response.status === 401) { window.location.href = '/'; return; }
    const data = await response.json();
    document.getElementById('total-portfolio-value').innerText = data.total_value.toLocaleString('ru-RU', {minimumFractionDigits: 2});

    const tbody = document.getElementById('bonds-table-body');
    tbody.innerHTML = '';

    if (!data.bonds || data.bonds.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Инвестиционный портфель пуст.</td></tr>`;
        return;
    }

    const esc = window.Common.escapeHtml;
    data.bonds.forEach(bond => {
        tbody.innerHTML += `
            <tr>
                <td><b>${esc(bond.name)}</b></td>
                <td><b class="isin-link" onclick="openBondChart(this.dataset.isin)" data-isin="${esc(bond.isin)}">${esc(bond.isin)}</b></td>
                <td>${bond.amount} шт.</td>
                <td>${bond.buy_price.toFixed(2)} ₽</td>
                <td class="text-primary"><b>${bond.nkd.toFixed(2)} ₽</b></td>
                <td class="text-info"><b>${bond.ytm.toFixed(2)} %</b></td>
                <td><button
                    onclick="sellTrigger(parseInt(this.dataset.id), this.dataset.name, parseFloat(this.dataset.price))"
                    data-id="${bond.id}"
                    data-name="${esc(bond.name)}"
                    data-price="${bond.last_price || bond.buy_price}"
                    class="btn btn-sm btn-outline-success">Продать</button></td>
            </tr>`;
    });
}

document.getElementById('addBondForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const isin = document.getElementById('bondIsin').value.trim();
    const amount = document.getElementById('bondAmount').value;
    const buy_price = document.getElementById('bondBuyPrice').value;
    const purchase_date = document.getElementById('bondDate').value;

    const response = await window.Common.csrfFetch('/api/add_bond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isin, amount, buy_price, purchase_date })
    });
    const data = await response.json();

    if (response.ok && data.status === "success") {
        window.Common.showSystemMessage(data.message, false);
        document.getElementById('addBondForm').reset();
        document.getElementById('bondDate').value = new Date().toISOString().split('T')[0];
        await loadDashboard();
    } else {
        window.Common.showSystemMessage(data.message, true);
    }
});

function sellTrigger(bondId, name, sellPrice) {
    window.Common.askConfirmation(`Вы действительно хотите зафиксировать продажу облигации ${name} и перевести её в архив сделок?`, async () => {
        const response = await window.Common.csrfFetch(`/api/sell_bond/${bondId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sell_price: sellPrice })
        });
        const data = await response.json();
        if (response.ok) { window.Common.showSystemMessage(data.message, false); await loadDashboard(); }
        else { window.Common.showSystemMessage(data.message, true); }
    });
}

async function handleLogout() {
    await window.Common.csrfFetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/';
}

async function fetchChartAnalytics() {
    const response = await fetch('/api/portfolio_stats');
    if (!response.ok) return;
    const chartData = await response.json();
    const ctx = document.getElementById('profitChart').getContext('2d');
    if (myChartInstance) myChartInstance.destroy();
    myChartInstance = new Chart(ctx, { type: 'bar', data: chartData, options: { responsive: true, maintainAspectRatio: false } });
}

loadDashboard();
