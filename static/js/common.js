window.Common = (function(){
    let infoModal = null;
    let confirmModal = null;

    function escapeHtml(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setTheme(mode) {
        const normalized = mode === 'dark' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-bs-theme', normalized);
        localStorage.setItem('portfolioTheme', normalized);
    }

    function initTheme() {
        const saved = localStorage.getItem('portfolioTheme');
        setTheme(saved === 'dark' ? 'dark' : 'light');
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-bs-theme');
        setTheme(current === 'dark' ? 'light' : 'dark');
    }

    function showSystemMessage(msg, isError = false) {
        const icon = document.getElementById('modalIconContainer');
        const title = document.getElementById('statusModalTitle');
        const msgEl = document.getElementById('statusModalMessage');
        if (!icon || !title || !msgEl) return;
        icon.className = isError ? "text-white bg-danger" : "text-white bg-success";
        icon.innerText = isError ? "✕" : "✓";
        title.innerText = isError ? "Ошибка!" : "Успешно!";
        title.className = isError ? "text-danger mb-2" : "text-success mb-2";
        msgEl.innerText = msg;

        if (!infoModal && document.getElementById('statusModal')) infoModal = new bootstrap.Modal(document.getElementById('statusModal'));
        if (infoModal) {
            infoModal.show();
            setTimeout(() => {
                const btn = document.querySelector('#statusModal [data-bs-dismiss="modal"]');
                if (btn) btn.focus();
            }, 50);
        }
    }

    function askConfirmation(msg, callback) {
        const msgEl = document.getElementById('confirmModalMessage') || document.getElementById('confirmDeleteMessage');
        if (!msgEl) return;
        msgEl.innerText = msg;
        if (!confirmModal) {
            const el = document.getElementById('confirmModal') || document.getElementById('confirmDeleteModal');
            if (el) confirmModal = new bootstrap.Modal(el);
        }
        const submitBtn = document.getElementById('confirmModalSubmitBtn') || document.getElementById('confirmDeleteSubmitBtn');
        if (!submitBtn) return;
        const newSubmitBtn = submitBtn.cloneNode(true);
        submitBtn.parentNode.replaceChild(newSubmitBtn, submitBtn);
        newSubmitBtn.addEventListener('click', () => { if (confirmModal) confirmModal.hide(); callback(); });
        if (confirmModal) {
            confirmModal.show();
            setTimeout(() => { try { newSubmitBtn.focus(); } catch (e) {} }, 50);
        }
    }

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    function getCsrfToken() {
        const raw = getCookie('XSRF-TOKEN');
        try { return raw ? decodeURIComponent(raw) : null; } catch { return raw; }
    }

    async function csrfFetch(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();
        const headers = new Headers(options.headers || {});
        if (method !== 'GET' && method !== 'HEAD') {
            const token = getCsrfToken();
            if (token) {
                headers.set('X-CSRFToken', token);
                headers.set('X-CSRF-Token', token);
            }
        }
        return fetch(url, { ...options, headers, credentials: 'same-origin' });
    }

    function showToast(msg, isError = false, isWarning = false) {
        const container = document.getElementById('toastContainer');
        if (!container) { showSystemMessage(msg, isError); return; }

        let bgClass, role, live, delay;
        if (isError)        { bgClass = 'bg-danger';  role = 'alert';  live = 'assertive'; delay = 6000; }
        else if (isWarning) { bgClass = 'bg-warning text-dark'; role = 'status'; live = 'polite'; delay = 5000; }
        else                { bgClass = 'bg-success'; role = 'status'; live = 'polite';    delay = 3000; }

        const toast = document.createElement('div');
        toast.className = `toast align-items-center border-0 ${isWarning ? 'text-dark' : 'text-white'} ${bgClass}`;
        toast.setAttribute('role', role);
        toast.setAttribute('aria-live', live);
        toast.setAttribute('aria-atomic', 'true');
        toast.style.cssText = 'overflow:hidden;position:relative;min-width:260px;';
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body fw-semibold">${escapeHtml(msg)}</div>
                <button type="button" class="btn-close ${isWarning ? '' : 'btn-close-white'} me-2 m-auto"
                        data-bs-dismiss="toast" aria-label="Закрыть"></button>
            </div>
            <div style="position:absolute;bottom:0;left:0;height:3px;width:100%;
                        background:rgba(0,0,0,.2);border-radius:0 0 var(--radius-xs,4px) var(--radius-xs,4px)">
                <div style="height:100%;width:100%;background:rgba(255,255,255,.5);
                            animation:toastProgress ${delay}ms linear forwards;transform-origin:left"></div>
            </div>`;
        container.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast, { delay });
        bsToast.show();
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    function countUp(el, end, {decimals = 0, suffix = '', prefix = '', duration = 650} = {}) {
        if (!el) return;
        const fmt = v => prefix + v.toLocaleString('ru-RU', {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + suffix;
        const startTime = performance.now();
        function step(now) {
            const p = Math.min((now - startTime) / duration, 1);
            const ease = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
            el.textContent = fmt(end * ease);
            if (p < 1) requestAnimationFrame(step);
            else el.textContent = fmt(end);
        }
        requestAnimationFrame(step);
    }

    async function handleLogout() {
        await csrfFetch('/api/auth/logout', { method: 'POST' });
        window.location.href = '/';
    }

    initTheme();

    return { showSystemMessage, askConfirmation, csrfFetch, escapeHtml, setTheme, initTheme, toggleTheme, showToast, handleLogout, countUp };
})();
