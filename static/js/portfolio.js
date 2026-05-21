let myChartInstance = null;
let marketChartInstance = null;
let infoModal = null;
let confirmModal = null;
let chartModal = null;

// Глобальные массивы хранения полной истории MOEX в памяти сессии браузера
let globalLabels = [];
let globalPrices = [];
let globalNkd = [];
let globalYtm = [];

document.getElementById('bondDate').value = new Date().toISOString().split('T')[0];

function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-bs-theme');
    html.setAttribute('data-bs-theme', currentTheme === 'dark' ? 'light' : 'dark');
}

function showSystemMessage(msg, isError = false) {
    const icon = document.getElementById('modalIconContainer');
    const title = document.getElementById('statusModalTitle');
    icon.className = isError ? "text-white bg-danger" : "text-white bg-success";
    icon.innerText = isError ? "✕" : "✓";
    title.innerText = isError ? "Ошибка!" : "Успешно!";
    title.className = isError ? "text-danger mb-2" : "text-success mb-2";
    document.getElementById('statusModalMessage').innerText = msg;
    if (!infoModal) infoModal = new bootstrap.Modal(document.getElementById('statusModal'));
    infoModal.show();
}

function askConfirmation(msg, callback) {
    document.getElementById('confirmModalMessage').innerText = msg;
    if (!confirmModal) confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
    const submitBtn = document.getElementById('confirmModalSubmitBtn');
    const newSubmitBtn = submitBtn.cloneNode(true);
    submitBtn.parentNode.replaceChild(newSubmitBtn, submitBtn);
    newSubmitBtn.addEventListener('click', () => { confirmModal.hide(); callback(); });
    confirmModal.show();
}

async function openBondChart(isin) {
    document.getElementById('chartModalIsinTitle').innerText = isin;
    if (!chartModal) chartModal = new bootstrap.Modal(document.getElementById('bondChartModal'));
    chartModal.show();

    // Загружаем ВСЮ пагинированную историю с бэкенда ОДНИМ запросом
    const response = await fetch(`/api/bond_chart/${isin}`);
    if (!response.ok) return;
    const resData = await response.json();

    globalLabels = resData.labels;
    globalPrices = resData.data;
    globalNkd = resData.nkd;
    globalYtm = resData.ytm;

    // Сбрасываем кнопки на интервал по умолчанию (Месяц)
    const buttons = document.querySelectorAll('#periodBtnGroup .btn');
    buttons.forEach(btn => btn.classList.remove('active'));
    document.querySelector('#periodBtnGroup [data-period="month"]').classList.add('active');

    applyChartScale('month');
}

function applyChartScale(period) {
    if (event && event.target && event.target.classList.contains('btn')) {
        const buttons = document.querySelectorAll('#periodBtnGroup .btn');
        buttons.forEach(btn => btn.classList.remove('active'));
        event.target.classList.add('active');
    }

    const totalPoints = globalLabels.length;
    if (totalPoints === 0) return;

    // Вычисляем левую видимую границу X-окна. Сами данные остаются в памяти для перетаскивания (Pan)
    let minIndex = 0;
    if (period === 'day') minIndex = Math.max(0, totalPoints - 2);
    else if (period === 'week') minIndex = Math.max(0, totalPoints - 7);
    else if (period === 'month') minIndex = Math.max(0, totalPoints - 30);
    else if (period === 'year') minIndex = Math.max(0, totalPoints - 252); // ~252 рабочих сессии в году

    const ctx = document.getElementById('marketBondChart').getContext('2d');
    if (marketChartInstance) marketChartInstance.destroy();

    marketChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: globalLabels,
            datasets: [{
                label: 'Рыночная стоимость (₽)',
                data: globalPrices,
                borderColor: '#0d6efd',
                backgroundColor: 'rgba(13, 110, 253, 0.04)',
                borderWidth: 2,
                fill: true,
                // Для "Всё время" отключаем кружки на точках ради колоссального прироста производительности
                pointRadius: period === 'all' ? 0 : (period === 'day' || period === 'week' ? 5 : 2)
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    // Умное масштабирование окна: загружено всё, но фокус на выбранном периоде!
                    min: period === 'all' ? globalLabels[0] : globalLabels[minIndex],
                    max: globalLabels[totalPoints - 1]
                }
            },
            plugins: {
                // КАСТОМНЫЙ ТУЛТИП: выводим одновременно Цену, НКД и YTM на выбранную дату
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `Цена бумаги: ${context.parsed.y} ₽`;
                        },
                        footer: function(tooltipItems) {
                            const dataIndex = tooltipItems[0].dataIndex;
                            return `НКД на дату: ${globalNkd[dataIndex]} ₽\nДоходность YTM: ${globalYtm[dataIndex]} %`;
                        }
                    }
                },
                // Инициализация свободного перетаскивания (зажатая кнопка мыши) и скролла зума
                zoom: {
                    pan: { enabled: true, mode: 'x' },
                    zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: 'x' }
                }
            }
        }
    });
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
    events.forEach(e => {
        list.innerHTML += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <div><b>${e.name}</b><br><small class="text-muted">${e.date}</small></div>
                <span class="badge bg-success font-monospace">+ ${e.total_payout} ₽</span>
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

    data.bonds.forEach(bond => {
        tbody.innerHTML += `
            <tr>
                <td><b>${bond.name}</b></td> <td><b class="isin-link" onclick="openBondChart('${bond.isin}')">${bond.isin}</b></td> <td>${bond.amount} шт.</td>
                <td>${bond.buy_price.toFixed(2)} ₽</td>
                <td class="text-primary"><b>${bond.nkd.toFixed(2)} ₽</b></td>
                <td class="text-info"><b>${bond.ytm.toFixed(2)} %</b></td>
                <td><button onclick="sellTrigger(${bond.id}, '${bond.name}')" class="btn btn-sm btn-outline-success">Продать</button></td>
            </tr>`;
    });
}

document.getElementById('addBondForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const isin = document.getElementById('bondIsin').value.trim();
    const amount = document.getElementById('bondAmount').value;
    const buy_price = document.getElementById('bondBuyPrice').value;
    const purchase_date = document.getElementById('bondDate').value;

    const response = await fetch('/api/add_bond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isin, amount, buy_price, purchase_date })
    });
    const data = await response.json();

    if (response.ok && data.status === "success") {
        showSystemMessage(data.message, false);
        document.getElementById('addBondForm').reset();
        document.getElementById('bondDate').value = new Date().toISOString().split('T')[0];
        await loadDashboard();
    } else {
        // Ошибка: Показываем модалку, но инпуты формы НЕ СБРАСЫВАЕМ
        showSystemMessage(data.message, true);
    }
});

function sellTrigger(bondId, name) {
    askConfirmation(`Вы действительно хотите зафиксировать продажу облигации ${name} и перевести её в архив сделок?`, async () => {
        const response = await fetch(`/api/sell_bond/${bondId}`, { method: 'POST' });
        const data = await response.json();
        if (response.ok) { showSystemMessage(data.message, false); await loadDashboard(); }
        else { showSystemMessage(data.message, true); }
    });
}

async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' });
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