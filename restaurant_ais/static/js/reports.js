// Отчётность: простая столбчатая диаграмма выручки по дням на <canvas> без библиотек.

function renderRevenueChart(canvasId, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !data.length) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width, height = canvas.height;
    const padding = 30;
    const max = Math.max(...data.map((d) => d.revenue), 1);
    const barWidth = (width - padding * 2) / data.length;

    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = "#e6ddd0";
    ctx.beginPath();
    ctx.moveTo(padding, height - padding);
    ctx.lineTo(width - 10, height - padding);
    ctx.stroke();

    data.forEach((d, i) => {
        const barHeight = ((height - padding * 2) * d.revenue) / max;
        const x = padding + i * barWidth + 4;
        const y = height - padding - barHeight;
        ctx.fillStyle = "#a8452f";
        ctx.fillRect(x, y, barWidth - 8, barHeight);
        ctx.fillStyle = "#766a5c";
        ctx.font = "10px sans-serif";
        ctx.save();
        ctx.translate(x + (barWidth - 8) / 2, height - padding + 12);
        ctx.rotate(-0.5);
        ctx.fillText(d.day.slice(5), 0, 0);
        ctx.restore();
    });
}
