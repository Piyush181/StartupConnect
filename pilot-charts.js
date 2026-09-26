// Draws a KPI trend chart into every <svg data-spark>: baseline, target, guardrail,
// verified readings and a dotted forecast to the pilot's end date.
(() => {
    const NS = 'http://www.w3.org/2000/svg';
    const day = value => new Date(`${value}T00:00:00Z`).getTime() / 86400000;
    const add = (svg, tag, attributes, text) => {
        const node = document.createElementNS(NS, tag);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
        if (text) node.textContent = text;
        svg.append(node);
        return node;
    };
    document.querySelectorAll('svg[data-spark]').forEach(svg => {
        const kpi = JSON.parse(svg.dataset.spark);
        const start = day(svg.dataset.start), end = day(svg.dataset.end);
        const values = [kpi.baseline, kpi.target, ...kpi.points.map(p => p.value)];
        if (kpi.guardrail !== null) values.push(kpi.guardrail);
        if (kpi.projected !== null) values.push(kpi.projected);
        let low = Math.min(...values), high = Math.max(...values);
        const pad = (high - low || 1) * 0.12; low -= pad; high += pad;
        const W = 320, H = 90, L = 4, R = 4, T = 6, B = 6;
        const x = d => L + (Math.min(Math.max(d, start), end) - start) / Math.max(1, end - start) * (W - L - R);
        const y = v => T + (high - v) / (high - low) * (H - T - B);
        const line = (value, cls) => add(svg, 'line', { x1: L, x2: W - R, y1: y(value), y2: y(value), class: cls });
        line(kpi.baseline, 'spark-baseline');
        line(kpi.target, 'spark-target');
        if (kpi.guardrail !== null) line(kpi.guardrail, 'spark-guardrail');
        const today = day(svg.dataset.today || new Date().toISOString().slice(0, 10));
        if (today > start && today < end) add(svg, 'line', { x1: x(today), x2: x(today), y1: T, y2: H - B, class: 'spark-today' });
        if (!kpi.points.length) {
            add(svg, 'text', { x: W / 2, y: H / 2 + 4, 'text-anchor': 'middle', class: 'spark-empty' }, 'No verified readings yet');
            return;
        }
        const coords = kpi.points.map(p => [x(day(p.date)), y(p.value)]);
        if (kpi.projected !== null) {
            const [lastX, lastY] = coords[coords.length - 1];
            add(svg, 'line', { x1: lastX, y1: lastY, x2: x(end), y2: y(kpi.projected), class: 'spark-forecast' });
        }
        add(svg, 'polyline', { points: coords.map(c => c.join(',')).join(' '), class: 'spark-line' });
        coords.forEach(([cx, cy], index) => {
            const dot = add(svg, 'circle', { cx, cy, r: 3.2, class: 'spark-dot' });
            add(dot, 'title', {}, `${kpi.points[index].date}: ${kpi.points[index].value} ${kpi.unit || ''}`);
        });
    });
})();
