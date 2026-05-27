window._activityPage = 1;
window._activityLoaded = false;

window.prfTab = function(idx) {
  document.querySelectorAll('.prf-tab').forEach((t, i) => t.classList.toggle('active', i === idx));
  document.querySelectorAll('.prf-panel').forEach((p, i) => p.classList.toggle('active', i === idx));
};

// Tab click listeners (replaces CSP-blocked onclick="prfTab(N)")
document.querySelectorAll('.prf-tab').forEach(function(btn) {
  btn.addEventListener('click', function() {
    window.prfTab(parseInt(this.dataset.tab, 10));
  });
});

document.getElementById('avatarFileInput')?.addEventListener('change', function () {
  document.getElementById('uploadZoneText').textContent =
    this.files[0] ? this.files[0].name : 'Нажмите для загрузки';
});

document.addEventListener('DOMContentLoaded', () => {
  // ── Logout ───────────────────────────────────────────────────────────
  document.getElementById('logoutBtn')?.addEventListener('click', () => {
    window.Common.handleLogout();
  });

  // ── Удаление аватара ─────────────────────────────────────────────────
  document.getElementById('deleteAvatarBtn')?.addEventListener('click', async () => {
    if (!confirm('Удалить аватар? Вместо него будут показаны ваши инициалы.')) return;
    const btn = document.getElementById('deleteAvatarBtn');
    btn.disabled = true; btn.textContent = 'Удаляем…';
    try {
      const res = await window.Common.csrfFetch('/api/profile/avatar', { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        window.Common.showToast(data.message);
        setTimeout(() => location.reload(), 900);
      } else {
        window.Common.showSystemMessage(data.message, true);
        btn.disabled = false; btn.textContent = 'Удалить аватар';
      }
    } catch {
      btn.disabled = false; btn.textContent = 'Удалить аватар';
    }
  });

  // ── Hero quick stats ─────────────────────────────────────────────────
  fetch('/api/profile/stats').then(r => r.json()).then(d => {
    const bc = document.getElementById('hsBondCount');
    const tv = document.getElementById('hsTotalValue');
    const sc = document.getElementById('hsSoldCount');
    if (bc) bc.textContent = d.bond_count ?? '—';
    if (sc) sc.textContent = d.sold_count ?? '—';
    if (tv && d.total_value != null) {
      tv.textContent = d.total_value.toLocaleString('ru-RU', {minimumFractionDigits: 0, maximumFractionDigits: 0}) + ' ₽';
    }
  }).catch(() => {});

  document.getElementById('changePasswordForm')?.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = document.getElementById('changePwBtn');
    btn.disabled = true; btn.textContent = 'Сохранение…';
    try {
      const res = await window.Common.csrfFetch('/api/auth/change_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_password: document.getElementById('oldPassword').value,
          new_password: document.getElementById('newPassword').value,
          confirm_password: document.getElementById('confirmPassword').value,
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        window.Common.showToast(data.message);
        e.target.reset();
      } else {
        window.Common.showSystemMessage(data.message, true);
      }
    } finally {
      btn.disabled = false; btn.textContent = 'Изменить пароль';
    }
  });

  // ── Telegram-бот ──────────────────────────────────────────────────
  async function loadTelegramStatus() {
    try {
      const res  = await fetch('/api/profile/telegram/status');
      const data = await res.json();
      const icon = document.getElementById('tgStatusIcon');
      const text = document.getElementById('tgStatusText');
      const desc = document.getElementById('tgStatusDesc');

      if (data.linked) {
        icon.textContent = '✅';
        text.textContent = 'Telegram привязан';
        const tgUser = data.telegram_username ? `@${data.telegram_username}` : '';
        desc.textContent = tgUser ? `${tgUser} · Бот @${data.bot_username}` : `Бот @${data.bot_username}`;
        document.getElementById('tgLinkedBlock').style.display = '';
        document.getElementById('tgUnlinkedBlock').style.display = 'none';
        document.getElementById('tgNotifCheck').checked = data.notifications;
        // Обновляем строку @username в панели «Учётная запись»
        const profileTgEl = document.getElementById('profileTgUsername');
        if (profileTgEl) {
          profileTgEl.textContent = tgUser || 'привязан';
          profileTgEl.style.color = tgUser ? '' : 'var(--text-tertiary)';
        }
      } else {
        icon.textContent = '🔗';
        text.textContent = 'Telegram не привязан';
        desc.textContent = 'Привяжите бот для уведомлений и 2FA';
        document.getElementById('tgLinkedBlock').style.display  = 'none';
        document.getElementById('tgUnlinkedBlock').style.display = '';
        // Сбрасываем строку @username
        const profileTgEl = document.getElementById('profileTgUsername');
        if (profileTgEl) {
          profileTgEl.textContent = 'не привязан';
          profileTgEl.style.color = 'var(--text-tertiary)';
        }
      }
    } catch {
      document.getElementById('tgStatusText').textContent = 'Ошибка загрузки';
    }
  }

  // Кнопка «Привязать»
  document.getElementById('tgLinkBtn')?.addEventListener('click', async () => {
    const btn = document.getElementById('tgLinkBtn');
    btn.disabled = true; btn.textContent = 'Получаем ссылку…';
    try {
      const res  = await window.Common.csrfFetch('/api/profile/telegram/link', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.deep_link) {
        const wrap = document.getElementById('tgDeepLinkWrap');
        const link = document.getElementById('tgDeepLink');
        link.href = data.deep_link;
        link.textContent = 'Открыть бот в Telegram →';
        wrap.style.display = '';
        btn.textContent = 'Обновить ссылку';
        btn.disabled = false;
      } else {
        window.Common.showSystemMessage(data.message || 'Ошибка', true);
        btn.disabled = false; btn.textContent = 'Привязать Telegram';
      }
    } catch {
      btn.disabled = false; btn.textContent = 'Привязать Telegram';
    }
  });

  // Переключатель Telegram-уведомлений
  document.getElementById('tgNotifCheck')?.addEventListener('change', async function () {
    try {
      const res  = await window.Common.csrfFetch('/api/profile/telegram/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: this.checked }),
      });
      const data = await res.json();
      if (res.ok) window.Common.showToast(data.message);
      else { window.Common.showSystemMessage(data.message, true); this.checked = !this.checked; }
    } catch { this.checked = !this.checked; }
  });

  // Кнопка «Отвязать»
  document.getElementById('tgUnlinkBtn')?.addEventListener('click', async () => {
    if (!confirm('Отвязать Telegram? Уведомления и 2FA будут отключены.')) return;
    const btn = document.getElementById('tgUnlinkBtn');
    btn.disabled = true; btn.textContent = 'Отвязываем…';
    try {
      const res  = await window.Common.csrfFetch('/api/profile/telegram/unlink', { method: 'POST' });
      const data = await res.json();
      if (res.ok) { window.Common.showToast(data.message); await loadTelegramStatus(); }
      else { window.Common.showSystemMessage(data.message, true); }
    } finally { btn.disabled = false; btn.textContent = 'Отвязать Telegram'; }
  });

  // ── Activity feed ──────────────────────────────────────────────────────
  window.loadActivity = async function (page) {
    page = Math.max(1, page || 1);
    window._activityPage = page;

    const listEl = document.getElementById('activityList');
    const loadEl = document.getElementById('activityLoading');
    const pagEl  = document.getElementById('activityPagination');
    if (loadEl) loadEl.style.display = 'block';
    if (listEl) listEl.innerHTML = '';
    if (pagEl)  pagEl.style.display = 'none';

    try {
      const res  = await fetch(`/api/profile/activity?page=${page}`);
      const data = await res.json();
      if (loadEl) loadEl.style.display = 'none';

      if (!data.entries || !data.entries.length) {
        if (listEl) listEl.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-tertiary)">Журнал пуст — входов в систему ещё не было.</div>';
        return;
      }

      const rows = data.entries.map(e => `
        <div style="display:flex;align-items:flex-start;gap:.75rem;padding:.8rem 1rem;border-bottom:1px solid var(--border-subtle)">
          <div style="width:34px;height:34px;border-radius:var(--radius-sm);background:var(--surface-2);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:1rem">${e.icon}</div>
          <div style="flex:1;min-width:0">
            <div style="font-size:.875rem;font-weight:600">${e.label}</div>
            <div style="font-size:.75rem;color:var(--text-tertiary);margin-top:.15rem">
              ${e.created_at}${e.ip_address && e.ip_address !== '—' ? ' · ' + e.ip_address : ''}
              ${e.details ? ' · <span style="font-style:italic">' + e.details + '</span>' : ''}
            </div>
          </div>
        </div>
      `).join('');
      if (listEl) listEl.innerHTML = rows;

      // Pagination
      if (data.pages > 1) {
        if (pagEl) pagEl.style.display = 'block';
        const pageInfo = document.getElementById('activityPageInfo');
        if (pageInfo) pageInfo.textContent = `Стр. ${data.page} из ${data.pages}`;
        const prevBtn = document.getElementById('activityPrevBtn');
        const nextBtn = document.getElementById('activityNextBtn');
        if (prevBtn) prevBtn.disabled = data.page <= 1;
        if (nextBtn) nextBtn.disabled = data.page >= data.pages;
      }

      window._activityLoaded = true;
    } catch {
      if (loadEl) loadEl.style.display = 'none';
      if (listEl) listEl.innerHTML = '<div style="text-align:center;padding:2rem;color:var(--text-tertiary)">Ошибка загрузки журнала.</div>';
    }
  };

  // Загружаем статус при открытии вкладок
  const origPrfTab = window.prfTab;
  window.prfTab = function (idx) {
    if (origPrfTab) origPrfTab(idx);
    if (idx === 2) loadTelegramStatus();
    if (idx === 3 && !window._activityLoaded) window.loadActivity(1);
  };
  // Обновляем слушатели вкладок, чтобы использовать расширенную версию prfTab
  document.querySelectorAll('.prf-tab').forEach(function(btn) {
    btn.onclick = null;
    btn.addEventListener('click', function() {
      window.prfTab(parseInt(this.dataset.tab, 10));
    });
  });
  // Пагинация активности
  var prevBtn = document.getElementById('activityPrevBtn');
  if (prevBtn) {
    prevBtn.addEventListener('click', function() { window.loadActivity(window._activityPage - 1); });
  }
  var nextBtn = document.getElementById('activityNextBtn');
  if (nextBtn) {
    nextBtn.addEventListener('click', function() { window.loadActivity(window._activityPage + 1); });
  }
  // Если уже открыта вкладка 2 — загружаем сразу
  if (document.getElementById('prf-panel-2').classList.contains('active')) {
    loadTelegramStatus();
  }
});
