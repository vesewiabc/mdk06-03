// Логика страницы заказа: фильтр блюд по названию/категории при добавлении в чек.

document.addEventListener("DOMContentLoaded", () => {
    const search = document.getElementById("dish-search");
    const picks = document.querySelectorAll(".dish-pick");
    if (!search) return;

    search.addEventListener("input", () => {
        const q = search.value.trim().toLowerCase();
        picks.forEach((el) => {
            const name = el.dataset.name.toLowerCase();
            el.style.display = name.includes(q) ? "" : "none";
        });
    });

    // подставляем dish_id в скрытое поле формы добавления позиции при клике "Добавить"
    document.querySelectorAll(".dish-pick [data-dish-id]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const form = btn.closest("form");
            const qtyInput = form.querySelector('input[name="qty"]');
            if (qtyInput && (!qtyInput.value || qtyInput.value < 1)) {
                qtyInput.value = 1;
            }
        });
    });
});
