/* =========================================================
   АИС «Гурман» — общий JS
   - тосты вместо flash
   - мобильное меню
   - живые часы
   - индикатор загрузки форм
   - подтверждения
   - умное автообновление
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {

    /* ---------------------------------------------------
       1. ТОСТЫ
       --------------------------------------------------- */
    const stack = document.createElement("div");
    stack.className = "toast-stack";
    document.body.appendChild(stack);

    const ICONS = {
        success: "✓",
        error:   "✕",
        warning: "!",
        info:    "i",
        message: "i",
    };

    function showToast(message, category = "info", timeout = 5000) {
        const el = document.createElement("div");
        el.className = `toast toast--${category}`;

        const icon = document.createElement("span");
        icon.className = "toast__icon";
        icon.textContent = ICONS[category] || ICONS.info;

        const body = document.createElement("div");
        body.className = "toast__body";
        body.textContent = message;

        const close = document.createElement("button");
        close.className = "toast__close";
        close.type = "button";
        close.setAttribute("aria-label", "Закрыть");
        close.textContent = "×";

        el.append(icon, body, close);
        stack.appendChild(el);

        const dismiss = () => {
            el.classList.add("is-leaving");
            setTimeout(() => el.remove(), 220);
        };

        close.addEventListener("click", dismiss);
        if (timeout > 0) setTimeout(dismiss, timeout);
    }

    document.querySelectorAll(".flash").forEach((node) => {
        const match = [...node.classList].find((c) => c.startsWith("flash--"));
        const category = match ? match.replace("flash--", "") : "info";
        showToast(node.textContent.trim(), category);
        node.remove();
    });

    window.showToast = showToast;

    /* ---------------------------------------------------
       2. МОБИЛЬНОЕ МЕНЮ
       --------------------------------------------------- */
    const sidebar = document.querySelector(".sidebar");
    const burger  = document.getElementById("sidebar-toggle");

    if (sidebar && burger) {
        const overlay = document.createElement("div");
        overlay.className = "sidebar-overlay";
        document.body.appendChild(overlay);

        const openMenu = () => {
            sidebar.classList.add("is-open");
            overlay.classList.add("is-open");
            document.body.style.overflow = "hidden";
        };
        const closeMenu = () => {
            sidebar.classList.remove("is-open");
            overlay.classList.remove("is-open");
            document.body.style.overflow = "";
        };
        const toggleMenu = () =>
            sidebar.classList.contains("is-open") ? closeMenu() : openMenu();

        burger.addEventListener("click", toggleMenu);
        overlay.addEventListener("click", closeMenu);

        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") closeMenu();
        });

        sidebar.querySelectorAll("nav a").forEach((a) => {
            a.addEventListener("click", () => {
                if (window.innerWidth <= 820) closeMenu();
            });
        });

        window.addEventListener("resize", () => {
            if (window.innerWidth > 820) closeMenu();
        });
    }

    /* ---------------------------------------------------
       3. ЖИВЫЕ ЧАСЫ
       --------------------------------------------------- */
    const clock = document.getElementById("clock");
    if (clock) {
        const tick = () => {
            const d = new Date();
            const date = d.toLocaleDateString("ru-RU", {
                day: "2-digit", month: "short", weekday: "short",
            });
            const time = d.toLocaleTimeString("ru-RU", {
                hour: "2-digit", minute: "2-digit",
            });
            clock.textContent = `${date} · ${time}`;
        };
        tick();
        setInterval(tick, 20000);
    }

        /* ---------------------------------------------------
       4. ПОДТВЕРЖДЕНИЯ + ИНДИКАТОР ЗАГРУЗКИ
       --------------------------------------------------- */
    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", (e) => {
            // 1) Сначала спрашиваем подтверждение.
            if (form.dataset.confirm && !confirm(form.dataset.confirm)) {
                e.preventDefault();
                return;
            }

            // 2) Только если сабмит реально уходит — показываем лоадер.
            const btn = form.querySelector("button[type=submit], button:not([type])");
            if (!btn || btn.classList.contains("is-loading")) return;

            btn.classList.add("is-loading");
            btn.disabled = true;

            // Страховка: если по какой-то причине страница не ушла
            // (ошибка валидации на клиенте), вернём кнопку через 8 с.
            setTimeout(() => {
                btn.classList.remove("is-loading");
                btn.disabled = false;
            }, 8000);
        });
    });

    /* ---------------------------------------------------
       6. УМНОЕ АВТООБНОВЛЕНИЕ
       --------------------------------------------------- */
    const autoRefresh = document.body.dataset.autorefresh;
    if (autoRefresh) {
        const ms = parseInt(autoRefresh, 10) * 1000;
        setInterval(() => {
            const a = document.activeElement;
            if (a && ["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName)) return;
            if (document.hidden) return;
            window.location.reload();
        }, ms);
    }

    /* ---------------------------------------------------
       7. ПЛАВНОЕ ПОЯВЛЕНИЕ КОНТЕНТА
       --------------------------------------------------- */
    const main = document.querySelector(".main");
    if (main) main.classList.add("page-enter");
});