const _currentUserId = parseInt(document.body.dataset.userId || '0', 10);

let _changePwTargetId = null;
let _changePwModal = null;
let _usersCache = [];

async function loadUsersList() {
  const tbody = document.getElementById('admin-users-table');
  tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-3">Загрузка…</td></tr>';
  const res = await window.Common.csrfFetch('/api/admin/users');
  if (!res.ok) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-danger text-center py-3">Ошибка загрузки</td></tr>';
    return;
  }
  const users = await res.json();
  _usersCache = users;
  const esc = window.Common.escapeHtml;
  tbody.innerHTML = users.map(u => {
    const isSelf = u.id === _currentUserId;
    const isRoot = u.username === 'root';
    const actions = isSelf
      ? '<span class="text-muted small">—</span>'
      : `<div class="d-flex gap-1 flex-wrap">
          ${!isRoot ? `<button class="btn btn-sm btn-outline-primary"
            data-action="changepw" data-uid="${u.id}" data-uname="${esc(u.username)}">Пароль</button>` : ''}
          <button class="btn btn-sm btn-outline-danger"
            data-action="delete" data-uid="${u.id}" data-uname="${esc(u.username)}">Удалить</button>
        </div>`;
    return `<tr>
      <td class="text-muted small">${u.id}</td>
      <td><b>${esc(u.username)}</b></td>
      <td><span class="badge ${u.is_admin ? 'bg-danger' : 'bg-secondary'}">${u.is_admin ? 'Админ' : 'Юзер'}</span></td>
      <td>${actions}</td>
    </tr>`;
  }).join('');

  // Populate broadcast user select
  const sel = document.getElementById('bcUserSelect');
  if (sel) {
    sel.innerHTML = users.map(u => `<option value="${u.id}">${esc(u.username)}</option>`).join('');
  }
}

// Delegate click for user actions
document.getElementById('admin-users-table')?.addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const uid = parseInt(btn.dataset.uid, 10);
  const uname = btn.dataset.uname;
  if (btn.dataset.action === 'delete') deleteUserTrigger(uid, uname);
  if (btn.dataset.action === 'changepw') changePasswordTrigger(uid, uname);
});

function deleteUserTrigger(userId, name) {
  window.Common.askConfirmation(`Удалить аккаунт «${name}» навсегда?`, async () => {
    const res = await window.Common.csrfFetch(`/api/admin/delete_user/${userId}`, { method: 'DELETE' });
    const data = await res.json();
    window.Common.showToast(data.message, !res.ok);
    loadUsersList();
  });
}

function changePasswordTrigger(userId, name) {
  _changePwTargetId = userId;
  document.getElementById('changePwUsername').textContent = name;
  document.getElementById('changePwNew').value = '';
  document.getElementById('changePwConfirm').value = '';
  if (!_changePwModal) _changePwModal = new bootstrap.Modal(document.getElementById('changePwModal'));
  _changePwModal.show();
}

document.getElementById('changePwSubmitBtn').addEventListener('click', async () => {
  const newPw = document.getElementById('changePwNew').value.trim();
  const confirm = document.getElementById('changePwConfirm').value.trim();
  if (!newPw || newPw.length < 8) { window.Common.showToast('Пароль должен содержать минимум 8 символов.', true); return; }
  if (newPw !== confirm) { window.Common.showToast('Пароли не совпадают.', true); return; }
  const btn = document.getElementById('changePwSubmitBtn');
  btn.disabled = true; btn.textContent = 'Сохранение…';
  try {
    const res = await window.Common.csrfFetch(`/api/admin/change_password/${_changePwTargetId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: newPw }),
    });
    const data = await res.json();
    if (res.ok) { if (_changePwModal) _changePwModal.hide(); window.Common.showToast(data.message); }
    else { window.Common.showToast(data.message, true); }
  } finally { btn.disabled = false; btn.textContent = 'Сохранить'; }
});

document.getElementById('adminCreateUserForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = document.getElementById('createUserBtn');
  btn.disabled = true; btn.textContent = 'Создание…';
  try {
    const res = await window.Common.csrfFetch('/api/admin/add_user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: document.getElementById('newUsername').value,
        password: document.getElementById('newPassword').value,
        is_admin: document.getElementById('isAdminCheck').checked,
      })
    });
    const data = await res.json();
    if (res.ok) { window.Common.showToast(data.message); e.target.reset(); loadUsersList(); }
    else { window.Common.showSystemMessage(data.message, true); }
  } finally { btn.disabled = false; btn.textContent = 'Создать'; }
});

document.getElementById('refreshUsersBtn')?.addEventListener('click', loadUsersList);

// ── Broadcast ────────────────────────────────────────────────────────────
document.querySelectorAll('input[name="bcRecipients"]').forEach(r => {
  r.addEventListener('change', () => {
    document.getElementById('bcUserSelectWrap').style.display =
      document.getElementById('bcSelect').checked ? '' : 'none';
  });
});

document.getElementById('bcSendBtn')?.addEventListener('click', async () => {
  const title = document.getElementById('bcTitle').value.trim();
  const body = document.getElementById('bcBody').value.trim();
  if (!title) { window.Common.showToast('Введите заголовок', true); return; }

  const channels = [];
  if (document.getElementById('bcChSite').checked) channels.push('site');
  if (document.getElementById('bcChTg').checked) channels.push('telegram');
  if (!channels.length) { window.Common.showToast('Выберите канал', true); return; }

  let recipients = 'all';
  if (document.getElementById('bcSelect').checked) {
    const sel = document.getElementById('bcUserSelect');
    recipients = Array.from(sel.selectedOptions).map(o => parseInt(o.value, 10));
    if (!recipients.length) { window.Common.showToast('Выберите получателей', true); return; }
  }

  const btn = document.getElementById('bcSendBtn');
  btn.disabled = true; btn.textContent = 'Отправка…';
  try {
    const res = await window.Common.csrfFetch('/api/admin/broadcast', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, body, recipients, channels }),
    });
    const data = await res.json();
    if (res.ok) {
      window.Common.showToast(data.message);
      document.getElementById('bcTitle').value = '';
      document.getElementById('bcBody').value = '';
    } else {
      window.Common.showSystemMessage(data.message, true);
    }
  } finally { btn.disabled = false; btn.textContent = 'Отправить'; }
});

loadUsersList();
