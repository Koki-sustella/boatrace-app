import { renderShell, loading } from "../components/shell";
import { venueName } from "../lib/constants";
import { getAllVenueCourseWinRates, type VenueCourseWinRateRow } from "../lib/queries";

export async function renderVenueCourseWinRatePage() {
  const content = renderShell({ title: "場別コース勝率", activeNav: "venue-win-rate" });
  loading(content);

  const rows = await getAllVenueCourseWinRates();
  const byVenue = new Map<string, VenueCourseWinRateRow[]>();
  for (const r of rows) {
    if (!byVenue.has(r.venue_code)) byVenue.set(r.venue_code, []);
    byVenue.get(r.venue_code)!.push(r);
  }
  const venues = Array.from(byVenue.keys()).sort();

  content.innerHTML = `
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:10px;">
      場ごと・進入コースごとの全選手合計の1着率。色が濃いほど勝率が高い。全期間・全グレード対象。
    </p>
    ${venues
      .map((v) => {
        const courseRows = byVenue.get(v)!;
        const cells = [1, 2, 3, 4, 5, 6]
          .map((course) => {
            const r = courseRows.find((x) => x.entry_course === course);
            if (!r || !r.starts_valid) return `<div class="grid-cell empty">${course}</div>`;
            const winRate = r.win_rate ?? 0;
            const color = colorForWinRate(winRate);
            return `<div class="grid-cell" style="background:${color}">
              ${(winRate * 100).toFixed(1)}<span class="n">${course}C</span>
            </div>`;
          })
          .join("");
        return `<div class="card"><div style="font-size:13px;margin-bottom:6px;">${venueName(v)}</div><div class="grid-course">${cells}</div></div>`;
      })
      .join("")}
  `;
}

function colorForWinRate(rate: number): string {
  // 1コース(highest, often ~0.5-0.6) -> green, 6コース(lowest, often <0.05) -> red.
  // Scale against a realistic 0-0.6 range rather than 0-1 so the color spread
  // is meaningful (course win rates never approach 100%).
  const t = Math.max(0, Math.min(1, rate / 0.6));
  const hue = t * 140; // 0=red .. 140=green
  return `hsl(${hue}, 60%, 45%)`;
}
