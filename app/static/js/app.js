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

// ---------- Immersion background: light rays + rising bubbles ----------
(function () {
    function build() {
        const bg = document.querySelector('.bg-parallax');
        if (!bg) return;

        // Light rays layer
        if (!document.querySelector('.rays')) {
            const rays = document.createElement('div');
            rays.className = 'rays';
            document.body.appendChild(rays);
        }

        // Rising bubbles (depth-varied sizes/speeds for a layered feel)
        if (!bg.querySelector('.bubble')) {
            const count = window.innerWidth < 768 ? 10 : 18;
            for (let i = 0; i < count; i++) {
                const b = document.createElement('span');
                b.className = 'bubble';
                const size = 4 + Math.random() * 18;          // 4–22px
                b.style.width = size + 'px';
                b.style.height = size + 'px';
                b.style.left = (Math.random() * 100) + 'vw';
                b.style.animationDuration = (9 + Math.random() * 16) + 's';
                b.style.animationDelay = (-Math.random() * 18) + 's';
                b.style.setProperty('--sway', (Math.random() * 60 - 30) + 'px');
                // smaller bubbles = "farther", lower opacity
                b.style.opacity = '';
                bg.appendChild(b);
            }
        }
    }
    document.addEventListener('DOMContentLoaded', build);
})();

// ---------- Multi-layer parallax (scroll + mouse, depth per layer) ----------
(function () {
    let mx = 0, my = 0;
    function apply() {
        const blobs = document.querySelectorAll('.bg-parallax .blob');
        const sy = window.scrollY || 0;
        blobs.forEach(function (el, i) {
            const depth = (i + 1) * 14;                       // farther layers move less
            const x = mx * depth;
            const y = my * depth + sy * 0.06 * (i + 1);
            el.style.transform = 'translate3d(' + x + 'px,' + y + 'px,0)';
        });
        // Gentle counter-parallax on the wave layer for depth.
        const waves = document.querySelector('.waves');
        if (waves) waves.style.transform = 'translateY(' + (sy * 0.04) + 'px)';
    }
    window.addEventListener('scroll', apply, { passive: true });
    window.addEventListener('mousemove', function (e) {
        mx = (e.clientX / window.innerWidth - 0.5);
        my = (e.clientY / window.innerHeight - 0.5);
        apply();
    }, { passive: true });
    document.addEventListener('DOMContentLoaded', apply);
})();
