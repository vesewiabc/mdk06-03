// Складской модуль: подсветка позиций с остатком ниже минимального.

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("tr[data-stock][data-min]").forEach((row) => {
        const stock = parseFloat(row.dataset.stock);
        const min = parseFloat(row.dataset.min);
        if (stock <= min) {
            row.classList.add("low-stock-row");
        }
    });
});