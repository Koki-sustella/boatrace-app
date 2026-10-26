export interface BarDatum {
  label: string;
  value: number | null;
  color?: string;
}

/** Minimal hand-rolled vertical bar chart with numeric labels above each bar
 * -- no charting library dependency, keeps the PWA bundle small. `maxValue`
 * fixes the y-scale (e.g. across venues) so bar heights stay comparable;
 * omit it to auto-scale to this chart's own max. */
export function renderBarChart(bars: BarDatum[], opts: { maxValue?: number; valueFormat?: (v: number) => string } = {}): string {
  const w = 300;
  const h = 150;
  const padTop = 22; // room for the value label above the tallest bar
  const padBottom = 18; // room for the x-axis label
  const padX = 6;
  const plotH = h - padTop - padBottom;

  const values = bars.map((b) => b.value ?? 0);
  const max = opts.maxValue ?? Math.max(...values, 0.01);
  const fmt = opts.valueFormat ?? ((v: number) => v.toFixed(1));

  const n = bars.length;
  const gap = 6;
  const barW = (w - padX * 2 - gap * (n - 1)) / n;

  const bodies = bars
    .map((b, i) => {
      const x = padX + i * (barW + gap);
      const v = b.value ?? 0;
      const barH = max > 0 ? (v / max) * plotH : 0;
      const y = padTop + (plotH - barH);
      const color = b.color ?? "var(--accent)";
      const labelText = b.value == null ? "-" : fmt(b.value);
      return `
        <text x="${x + barW / 2}" y="${y - 5}" text-anchor="middle" font-size="10" fill="var(--text)">${labelText}</text>
        <rect x="${x}" y="${y}" width="${barW}" height="${Math.max(barH, 1)}" rx="2" fill="${color}" />
        <text x="${x + barW / 2}" y="${h - 4}" text-anchor="middle" font-size="10" fill="var(--text-dim)">${b.label}</text>
      `;
    })
    .join("");

  return `
    <svg class="bar-chart-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
      ${bodies}
    </svg>
  `;
}
