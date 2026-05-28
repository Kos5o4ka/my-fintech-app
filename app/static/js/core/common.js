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

    const _SUN_SVG = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="2.5"/><line x1="8" y1="1" x2="8" y2="3"/><line x1="8" y1="13" x2="8" y2="15"/><line x1="1" y1="8" x2="3" y2="8"/><line x1="13" y1="8" x2="15" y2="8"/><line x1="3.05" y1="3.05" x2="4.46" y2="4.46"/><line x1="11.54" y1="11.54" x2="12.95" y2="12.95"/><line x1="3.05" y1="12.95" x2="4.46" y2="11.54"/><line x1="11.54" y1="4.46" x2="12.95" y2="3.05"/></svg>`;
    const _MOON_SVG = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7z"/></svg>`;

    function _updateThemeIcon(mode) {
        document.querySelectorAll('.theme-icon').forEach(el => {
            el.innerHTML = mode === 'dark' ? _SUN_SVG : _MOON_SVG;
            el.classList.remove('theme-icon-spin');
            void el.offsetWidth; // reflow to restart animation
            el.classList.add('theme-icon-spin');
        });
    }

    function setTheme(mode) {
        const normalized = mode === 'dark' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-bs-theme', normalized);
        localStorage.setItem('portfolioTheme', normalized);
        _updateThemeIcon(normalized);
    }

    function initTheme() {
        const saved = localStorage.getItem('portfolioTheme');
        setTheme(saved === 'dark' ? 'dark' : 'light');
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-bs-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        if (document.startViewTransition) {
            document.startViewTransition(() => setTheme(next));
        } else {
            setTheme(next);
        }
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
        const c = document.cookie.split(';').find(c => c.trim().startsWith(name + '='));
        return c ? c.trim().slice(name.length + 1) : null;
    }

    function getCsrfToken() {
        const raw = getCookie('XSRF-TOKEN');
        if (raw) { try { return decodeURIComponent(raw); } catch { return raw; } }
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : null;
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

        // Swipe-to-dismiss (mobile: swipe right ≥ 80px)
        let _tx = 0;
        toast.addEventListener('touchstart', e => { _tx = e.touches[0].clientX; }, { passive: true });
        toast.addEventListener('touchmove', e => {
            const dx = e.touches[0].clientX - _tx;
            if (dx > 0) { toast.style.transform = `translateX(${dx}px)`; toast.style.opacity = String(1 - dx / 200); }
        }, { passive: true });
        toast.addEventListener('touchend', e => {
            const dx = e.changedTouches[0].clientX - _tx;
            if (dx > 80) { bsToast.hide(); }
            else { toast.style.transform = ''; toast.style.opacity = ''; }
        }, { passive: true });
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
