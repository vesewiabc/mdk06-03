// Складской модуль: подсветка позиций с остатком ниже минимального, авто-расчёт
// изменения при инвентаризации.

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("tr[data-stock][data-min]").forEach((row) => {
        const stock = parseFloat(row.dataset.stock);
        const min = parseFloat(row.dataset.min);
        if (stock <= min) {
            row.classList.add("low-stock-row");
            row.style.background = "#fbeecd";
        }
    });
});
