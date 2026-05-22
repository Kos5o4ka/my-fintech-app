window.Sidebar = (function () {
    const STORAGE_KEY = 'sidebarCollapsed';

    function isCollapsed() {
        return localStorage.getItem(STORAGE_KEY) === '1';
    }

    function setCollapsed(val) {
        const layout = document.getElementById('appLayout');
        if (!layout) return;
        if (val) {
            layout.classList.add('sidebar-collapsed');
            localStorage.setItem(STORAGE_KEY, '1');
        } else {
            layout.classList.remove('sidebar-collapsed');
            localStorage.removeItem(STORAGE_KEY);
        }
    }

    function toggle() {
        setCollapsed(!isCollapsed());
    }

    function init() {
        const layout = document.getElementById('appLayout');
        if (!layout) return;

        if (isCollapsed()) layout.classList.add('sidebar-collapsed');

        const btn = document.getElementById('sidebarToggle');
        if (btn) btn.addEventListener('click', toggle);
    }

    document.addEventListener('DOMContentLoaded', init);

    return { toggle, setCollapsed };
})();
