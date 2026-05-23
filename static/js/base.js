/* ── Page transitions ───────────────────────────────────────────── */
(function () {
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href]');
    if (!a) return;
    var href = a.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('http') ||
        href.startsWith('mailto') || a.target === '_blank' ||
        a.hasAttribute('data-bs-toggle') || e.ctrlKey || e.metaKey) return;
    var main = document.getElementById('appMain');
    if (!main) return;
    e.preventDefault();
    main.classList.add('page-leaving');
    setTimeout(function () { window.location.href = href; }, 170);
  });
})();

/* ── Common.shake — form shake animation ───────────────────────── */
(function () {
  var orig = window.Common;
  if (!orig) return;
  orig.shake = function (el) {
    if (!el) return;
    el.classList.remove('form-shake');
    void el.offsetWidth; // reflow to restart animation
    el.classList.add('form-shake');
    el.addEventListener('animationend', function h() {
      el.classList.remove('form-shake');
      el.removeEventListener('animationend', h);
    });
  };
})();

/* ── Bell dropdown ──────────────────────────────────────────────── */
(function () {
  var _bellLoaded = false;

  function renderBellBody(data) {
    var body = document.getElementById('bellDropdownBody');
    if (!body) return;
    if (!data.events || data.events.length === 0) {
      body.innerHTML = '<div style="text-align:center;padding:1.5rem;color:var(--text-tertiary);font-size:.82rem">Нет ближайших купонов (7 дней)</div>';
      return;
    }
    var html = '';
    data.events.forEach(function (e) {
      var daysLabel = e.days_left === 0 ? 'Сегодня' : e.days_left === 1 ? 'Завтра' : 'Через ' + e.days_left + ' дн.';
      var couponTotal = e.coupon_value ? ' · ' + (parseFloat(e.coupon_value) * e.amount).toFixed(2) + ' ₽' : '';
      html += '<div style="padding:.6rem 1rem;border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;gap:.65rem">'
        + '<div style="width:36px;height:36px;border-radius:var(--radius-sm);background:rgba(var(--accent-rgb),.1);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:.9rem">💰</div>'
        + '<div style="flex:1;min-width:0">'
        + '<div style="font-size:.8rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + (e.name || e.isin) + '</div>'
        + '<div style="font-size:.72rem;color:var(--text-tertiary)">' + daysLabel + ' · ' + e.coupon_date + couponTotal + '</div>'
        + '</div>'
        + '</div>';
    });
    body.innerHTML = html;
  }

  function loadBellData() {
    fetch('/api/notifications/upcoming?days=7')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var badge = document.getElementById('bellBadge');
        if (badge) {
          if (data.count > 0) {
            badge.textContent = data.count > 9 ? '9+' : data.count;
            badge.style.display = 'inline-flex';
          } else {
            badge.style.display = 'none';
          }
        }
        renderBellBody(data);
        _bellLoaded = true;
      })
      .catch(function () {});
  }

  window.toggleBellDropdown = function (e) {
    if (e) e.stopPropagation();
    var dd = document.getElementById('bellDropdown');
    if (!dd) return;
    var isOpen = dd.style.display !== 'none';
    dd.style.display = isOpen ? 'none' : 'block';
    if (!isOpen && !_bellLoaded) loadBellData();
  };

  // Close on outside click
  document.addEventListener('click', function (e) {
    var wrap = document.getElementById('sidebarBellWrap');
    if (wrap && !wrap.contains(e.target)) {
      var dd = document.getElementById('bellDropdown');
      if (dd) dd.style.display = 'none';
    }
  });

  // Load badge count on page load (no dropdown)
  document.addEventListener('DOMContentLoaded', loadBellData);
})();
