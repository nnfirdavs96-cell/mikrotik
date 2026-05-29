// Ask for confirmation before destructive POST actions.
document.addEventListener('submit', function (e) {
    const form = e.target;
    if (form.classList.contains('js-confirm')) {
        if (!window.confirm('Вы уверены? Действие нельзя отменить.')) {
            e.preventDefault();
        }
    }
});

// ---------- Theme toggle (light/dark, persisted) ----------
(function () {
    function updateIcon(theme) {
        document.querySelectorAll('.theme-toggle i').forEach(function (ic) {
            ic.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
        });
    }
    window.toggleTheme = function () {
        const html = document.documentElement;
        const next = html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-bs-theme', next);
        try { localStorage.setItem('theme', next); } catch (e) {}
        updateIcon(next);
    };
    document.addEventListener('DOMContentLoaded', function () {
        updateIcon(document.documentElement.getAttribute('data-bs-theme') || 'light');
    });
})();

// ---------- Collapsible sidebar ----------
(function () {
    window.toggleSidebar = function () {
        const collapsed = document.body.classList.toggle('sb-collapsed');
        try { localStorage.setItem('sb', collapsed ? '1' : '0'); } catch (e) {}
    };
    document.addEventListener('DOMContentLoaded', function () {
        let saved = null;
        try { saved = localStorage.getItem('sb'); } catch (e) {}
        // On small screens start collapsed; on desktop respect the saved choice.
        if (window.innerWidth < 768 || saved === '1') {
            document.body.classList.add('sb-collapsed');
        }
    });
})();

// ---------- Parallax background (scroll + mouse) ----------
(function () {
    let mx = 0, my = 0;
    function apply() {
        const blobs = document.querySelectorAll('.bg-parallax .blob');
        const sy = window.scrollY || 0;
        blobs.forEach(function (el, i) {
            const depth = (i + 1) * 10;
            const x = mx * depth;
            const y = my * depth + sy * 0.05 * (i + 1);
            el.style.transform = 'translate3d(' + x + 'px,' + y + 'px,0)';
        });
    }
    window.addEventListener('scroll', apply, { passive: true });
    window.addEventListener('mousemove', function (e) {
        mx = (e.clientX / window.innerWidth - 0.5);
        my = (e.clientY / window.innerHeight - 0.5);
        apply();
    }, { passive: true });
    document.addEventListener('DOMContentLoaded', apply);
})();
