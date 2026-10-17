export interface TrendPoint {
  label: string;
  value: number | null;
}

/** Minimal hand-rolled SVG line chart -- no charting library dependency,
 * keeps the PWA bundle small for mobile. Lower values plotted higher
 * (average finish position: 1st place should appear at the top). */
export function renderTrendChart(points: TrendPoint[], opts: { invert?: boolean } = {}): string {
  const valid = points.filter((p) => p.value != null) as { label: string; value: number }[];
  if (valid.length < 2) {
    return `<div class="empty">データが不足しています</div>`;
  }
  const w = 300;
  const h = 100;
  const padX = 8;
  const padY = 12;
  const values = valid.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const xStep = (w - padX * 2) / (points.length - 1);
  const yFor = (v: number) => {
    // t=0 at the lowest value, t=1 at the highest. By default (invert=false)
    // low values (best average finish) are plotted near the top (small y).
    const t = (v - min) / range;
    const norm = opts.invert ? 1 - t : t;
    return padY + norm * (h - padY * 2);
  };

  let d = "";
  points.forEach((p, i) => {
    if (p.value == null) return;
    const x = padX + i * xStep;
    const y = yFor(p.value);
    d += (d ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1) + " ";
  });

  const dots = points
    .map((p, i) => {
      if (p.value == null) return "";
      const x = padX + i * xStep;
      const y = yFor(p.value);
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" fill="var(--accent)"><title>${p.label}: ${p.value.toFixed(2)}</title></circle>`;
    })
    .join("");

  return `
    <svg class="trend-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <path d="${d}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke" />
      ${dots}
    </svg>
  `;
}
