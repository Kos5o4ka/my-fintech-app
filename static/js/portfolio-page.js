// Teleport drawer & overlay out of .page-enter so position:fixed works correctly
document.addEventListener('DOMContentLoaded', () => {
  ['bondDrawer', 'drawerOverlay'].forEach(id => {
    const el = document.getElementById(id);
    if (el) document.body.appendChild(el);
  });
});

function openDrawer() {
  document.getElementById('bondDrawer').classList.add('open');
  document.getElementById('drawerOverlay').classList.add('open');
  document.body.style.overflow = 'hidden';
  
  const notesEl = document.getElementById('bondNotes');
  if (notesEl) notesEl.value = '';
  
  const drawerTitle = document.querySelector('.drawer-title');
  if (drawerTitle) drawerTitle.textContent = 'Добавить облигацию';
  
  const addBtn = document.getElementById('addBondBtn');
  if (addBtn) {
    addBtn.textContent = 'Добавить в портфель';
    addBtn.onclick = function () {
      document.getElementById('addBondForm').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
    };
  }
  setTimeout(() => document.getElementById('bondIsin')?.focus(), 350);
}

function closeDrawer() {
  document.getElementById('bondDrawer').classList.remove('open');
  document.getElementById('drawerOverlay').classList.remove('open');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

function filterBondsTable(q) {
  const rows = document.querySelectorAll('#bonds-table-body tr[data-name]');
  const s = q.toLowerCase();
  rows.forEach(r => {
    const show = !s || r.dataset.name?.toLowerCase().includes(s) || r.dataset.isin?.toLowerCase().includes(s);
    r.style.display = show ? '' : 'none';
  });
}
