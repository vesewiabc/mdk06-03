/* =========================================================
   Отчётность: круговая диаграмма + столбчатая + всплывашки
   Без сторонних библиотек, чистый Canvas 2D
   ========================================================= */

const PALETTE = [
    "#e11d48", "#2563eb", "#16a34a", "#d97706",
    "#7c3aed", "#0891b2", "#be123c", "#65a30d",
    "#c026d3", "#0284c7"
];

/* ---------- Утилиты ---------- */
function fmtMoney(n) {
    return new Intl.NumberFormat("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(n) + " ₽";
}

function shortMoney(v) {
    if (v >= 1000000) return (v / 1000000).toFixed(1) + " млн";
    if (v >= 1000)    return (v / 1000).toFixed(0) + " тыс";
    return String(Math.round(v));
}

function niceMax(v) {
    if (v <= 0) return 100;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / p;
    let m;
    if (n <= 1) m = 1;
    else if (n <= 2) m = 2;
    else if (n <= 5) m = 5;
    else m = 10;
    return m * p;
}

function roundRect(ctx, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
}

/* ---------- Тултип ---------- */
function tooltipEl() {
    let el = document.getElementById("chart-tooltip");
    if (!el) {
        el = document.createElement("div");
        el.id = "chart-tooltip";
        el.className = "chart-tooltip";
        document.body.appendChild(el);
    }
    return el;
}
function showTooltip(html, clientX, clientY) {
    const el = tooltipEl();
    el.innerHTML = html;
    el.style.display = "block";
    requestAnimationFrame(() => {
        const rect = el.getBoundingClientRect();
        const pad = 16;
        let left = clientX + pad;
        let top  = clientY + pad;
        if (left + rect.width > window.innerWidth - 10)  left = clientX - rect.width - pad;
        if (top + rect.height > window.innerHeight - 10) top  = clientY - rect.height - pad;
        el.style.left = left + "px";
        el.style.top  = top  + "px";
    });
}
function hideTooltip() {
    const el = document.getElementById("chart-tooltip");
    if (el) el.style.display = "none";
}

/* =========================================================
   КРУГОВАЯ ДИАГРАММА
   ========================================================= */
function renderDonut(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data.length) return;

    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth  || 300;
    const cssH = canvas.clientHeight || 300;
    canvas.width  = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const cx = cssW / 2;
    const cy = cssH / 2;
    const outerR = Math.min(cx, cy) - 8;
    const innerR = outerR * 0.60;

    const total = data.reduce((s, d) => s + d.value, 0) || 1;
    let start = -Math.PI / 2;

    const segments = data.map((d, i) => {
        const angle = (d.value / total) * Math.PI * 2;
        const seg = {
            start,
            end: start + angle,
            data: d,
            color: PALETTE[i % PALETTE.length],
        };
        start += angle;
        return seg;
    });

    let hoveredIdx = -1;

    function draw() {
        ctx.clearRect(0, 0, cssW, cssH);

        segments.forEach((seg, i) => {
            const isHover = i === hoveredIdx;
            const r1 = isHover ? innerR - 3 : innerR;
            const r2 = isHover ? outerR + 6 : outerR;

            ctx.beginPath();
            ctx.arc(cx, cy, r2, seg.start, seg.end);
            ctx.arc(cx, cy, r1, seg.end, seg.start, true);
            ctx.closePath();
            ctx.fillStyle = seg.color;
            ctx.fill();

            ctx.strokeStyle = "#fff";
            ctx.lineWidth = 2;
            ctx.stroke();
        });

        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const active = hoveredIdx >= 0 ? segments[hoveredIdx].data : null;

        if (active) {
            ctx.fillStyle = "#0f172a";
            ctx.font = "700 17px Inter, Segoe UI, sans-serif";
            ctx.fillText(fmtMoney(active.value), cx, cy - 10);
            ctx.fillStyle = "#64748b";
            ctx.font = "500 12px Inter, Segoe UI, sans-serif";
            const pct = ((active.value / total) * 100).toFixed(1) + "%";
            ctx.fillText(pct, cx, cy + 12);
        } else {
            ctx.fillStyle = "#0f172a";
            ctx.font = "700 20px Inter, Segoe UI, sans-serif";
            ctx.fillText(fmtMoney(total), cx, cy - 8);
            ctx.fillStyle = "#94a3b8";
            ctx.font = "500 11px Inter, Segoe UI, sans-serif";
            ctx.fillText("за период", cx, cy + 14);
        }
    }

    draw();

    canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const dx = x - cx, dy = y - cy;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < innerR - 2 || dist > outerR + 8) {
            if (hoveredIdx !== -1) { hoveredIdx = -1; draw(); }
            hideTooltip();
            canvas.style.cursor = "default";
            return;
        }

        let angle = Math.atan2(dy, dx);
        const startTop = -Math.PI / 2;
        while (angle < startTop) angle += Math.PI * 2;
        while (angle >= startTop + Math.PI * 2) angle -= Math.PI * 2;

        const idx = segments.findIndex(s => angle >= s.start && angle < s.end);
        if (idx !== hoveredIdx) {
            hoveredIdx = idx;
            draw();
        }

        if (idx >= 0) {
            const d = segments[idx].data;
            showTooltip(
                `<b>${d.label}</b><br>Выручка: ${fmtMoney(d.value)}` +
                (d.qty != null ? `<br>Продано: ${d.qty} шт` : ""),
                e.clientX, e.clientY
            );
            canvas.style.cursor = "pointer";
        }
    });

    canvas.addEventListener("mouseleave", () => {
        if (hoveredIdx !== -1) { hoveredIdx = -1; draw(); }
        hideTooltip();
        canvas.style.cursor = "default";
    });
}

/* =========================================================
   СТОЛБЧАТАЯ ДИАГРАММА
   ========================================================= */
function renderBarChart(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data.length) return;

    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth  || 700;
    const cssH = canvas.clientHeight || 280;
    canvas.width  = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const pad = { top: 20, right: 16, bottom: 38, left: 56 };
    const chartW = cssW - pad.left - pad.right;
    const chartH = cssH - pad.top  - pad.bottom;

    const max = Math.max(...data.map(d => d.value), 1);
    const nice = niceMax(max);
    const lines = 4;

    const gap = 12;
    const barW = Math.max(10, (chartW - gap * (data.length - 1)) / data.length);
    const bars = [];
    let hoveredIdx = -1;

    function draw() {
        ctx.clearRect(0, 0, cssW, cssH);

        ctx.font = "11px Inter, Segoe UI, sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (let i = 0; i <= lines; i++) {
            const v = (nice / lines) * i;
            const y = pad.top + chartH - (v / nice) * chartH;

            ctx.strokeStyle = "#eef1f6";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(pad.left + chartW, y);
            ctx.stroke();

            ctx.fillStyle = "#94a3b8";
            ctx.fillText(shortMoney(v), pad.left - 8, y);
        }

        data.forEach((d, i) => {
            const x = pad.left + i * (barW + gap);
            const h = Math.max(2, (d.value / nice) * chartH);
            const y = pad.top + chartH - h;
            const isHover = i === hoveredIdx;

            const grad = ctx.createLinearGradient(0, y, 0, pad.top + chartH);
            if (isHover) {
                grad.addColorStop(0, "#be123c");
                grad.addColorStop(1, "#e11d48");
            } else {
                grad.addColorStop(0, "#e11d48");
                grad.addColorStop(1, "#fda4af");
            }
            ctx.fillStyle = grad;
            roundRect(ctx, x, y, barW, h, 6);
            ctx.fill();

            bars[i] = { x, y, w: barW, h };

            ctx.fillStyle = "#64748b";
            ctx.font = "10.5px Inter, Segoe UI, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillText(d.label.slice(5), x + barW / 2, pad.top + chartH + 8);
        });
    }

    draw();

    canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        const idx = bars.findIndex(b =>
            b && x >= b.x - 6 && x <= b.x + b.w + 6 &&
            y >= pad.top - 4 && y <= pad.top + chartH + 4
        );

        if (idx !== hoveredIdx) {
            hoveredIdx = idx;
            draw();
        }

        if (idx >= 0) {
            const d = data[idx];
            showTooltip(
                `<b>${d.label}</b><br>Выручка: ${fmtMoney(d.value)}`,
                e.clientX, e.clientY
            );
            canvas.style.cursor = "pointer";
        } else {
            hideTooltip();
            canvas.style.cursor = "default";
        }
    });

    canvas.addEventListener("mouseleave", () => {
        if (hoveredIdx !== -1) { hoveredIdx = -1; draw(); }
        hideTooltip();
        canvas.style.cursor = "default";
    });
}

/* =========================================================
   ЛЕГЕНДА
   ========================================================= */
function renderLegend(elId, data) {
    const el = document.getElementById(elId);
    if (!el) return;
    const total = data.reduce((s, d) => s + d.value, 0) || 1;
    el.innerHTML = data.map((d, i) => {
        const pct = ((d.value / total) * 100).toFixed(1);
        return `<div class="legend-row">
            <span class="legend-dot" style="background:${PALETTE[i % PALETTE.length]}"></span>
            <span class="legend-name" title="${d.label}">${d.label}</span>
            <span class="legend-val">${pct}%</span>
        </div>`;
    }).join("");
}

/* =========================================================
   ИНИЦИАЛИЗАЦИЯ
   ========================================================= */
document.addEventListener("DOMContentLoaded", () => {
    let DATA = { donut: [], bar: [] };
    const dataEl = document.getElementById("chart-data");
    if (dataEl) {
        try {
            DATA = JSON.parse(dataEl.textContent);
        } catch (e) {
            console.error("Ошибка чтения chart-data:", e);
        }
    }
    const donutData = DATA.donut || [];
    const barData   = DATA.bar   || [];

    if (donutData.length) {
        renderDonut("chart-donut", donutData);
        renderLegend("chart-donut-legend", donutData);
    } else {
        const c = document.getElementById("chart-donut");
        if (c) c.parentElement.innerHTML =
            '<p class="empty-state" style="margin:0;">Нет данных за выбранный период</p>';
    }

    if (barData.length) {
        renderBarChart("chart-bar", barData);
    } else {
        const c = document.getElementById("chart-bar");
        if (c) c.parentElement.innerHTML =
            '<p class="empty-state" style="margin:0;">Нет данных за выбранный период</p>';
    }
});