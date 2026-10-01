// Логика страницы заказа: фильтр блюд по названию/категории
// и валидация количества при добавлении в чек.

document.addEventListener("DOMContentLoaded", () => {
    // --- Поиск блюд ---
    const search = document.getElementById("dish-search");
    const picks = document.querySelectorAll(".dish-pick");

    if (search) {
        search.addEventListener("input", () => {
            const q = search.value.trim().toLowerCase();
            picks.forEach((el) => {
                const name = (el.dataset.name || "").toLowerCase();
                el.style.display = name.includes(q) ? "" : "none";
            });
        });
    }

    // --- Валидация qty (1–99) при любом изменении ---
    document.querySelectorAll(".dish-pick input[name='qty']").forEach((input) => {
        input.addEventListener("change", () => {
            let v = parseInt(input.value, 10);
            if (isNaN(v) || v < 1) v = 1;
            if (v > 99) v = 99;
            input.value = v;
        });
    });
});