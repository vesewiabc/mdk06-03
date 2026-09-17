// Общие клиентские сценарии: автоскрытие флеш-сообщений, подтверждение
// действий, автообновление экранов кухни/зала.

document.addEventListener("DOMContentLoaded", () => {
    // автоскрытие flash-сообщений через 4 секунды
    document.querySelectorAll(".flash").forEach((el) => {
        setTimeout(() => {
            el.style.transition = "opacity .4s ease";
            el.style.opacity = "0";
            setTimeout(() => el.remove(), 400);
        }, 4000);
    });

    // подтверждение перед необратимыми действиями
    document.querySelectorAll("[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (e) => {
            if (!confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });

    // автообновление страниц с data-autorefresh (кухня/бар, схема зала)
    const autoRefresh = document.body.dataset.autorefresh;
    if (autoRefresh) {
        setInterval(() => window.location.reload(), parseInt(autoRefresh, 10) * 1000);
    }
});
