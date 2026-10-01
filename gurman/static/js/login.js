/* Подстановка демо-данных в форму входа (только в DEBUG). */
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".demo__table tbody tr").forEach((row) => {
        row.addEventListener("click", () => {
            const cells = row.querySelectorAll("td");
            const user = cells[1]?.innerText.trim();
            const pass = cells[2]?.innerText.trim();
            if (!user || !pass) return;
            const u = document.getElementById("username");
            const p = document.getElementById("password");
            u.value = user;
            p.value = pass;
            [u, p].forEach((el) => {
                el.style.transition = "background .3s";
                el.style.background = "#fef2f4";
                setTimeout(() => (el.style.background = ""), 500);
            });
        });
    });
});