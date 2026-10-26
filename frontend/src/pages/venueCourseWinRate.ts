import { renderShell, loading } from "../components/shell";
import { venueName } from "../lib/constants";
import { renderBarChart } from "../components/barChart";
import { getAllVenueCourseWinRates, type VenueCourseWinRateRow } from "../lib/queries";

const MAX_RATE = 0.6; // fixed y-scale so bars are comparable across venues

export async function renderVenueCourseWinRatePage() {
  const content = renderShell({ title: "場別コース勝率", activeNav: "venue-win-rate" });
  loading(content);

  const rows = await getAllVenueCourseWinRates();
  const byVenue = new Map<string, VenueCourseWinRateRow[]>();
  for (const r of rows) {
    if (!byVenue.has(r.venue_code)) byVenue.set(r.venue_code, []);
    byVenue.get(r.venue_code)!.push(r);
  }

  content.innerHTML = `
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:10px;">
      場ごと・進入コースごとの全選手合計の1着率。全期間・全グレード対象。
    </p>
    <div class="field">
      <label for="sort-by">並び替え</label>
      <select id="sort-by">
        <option value="venue">場名順</option>
        ${[1, 2, 3, 4, 5, 6].map((c) => `<option value="${c}">${c}コース勝率が高い順</option>`).join("")}
      </select>
    </div>
    <div id="venue-list"></div>
  `;

  const listEl = content.querySelector<HTMLElement>("#venue-list")!;
  const sortSel = content.querySelector<HTMLSelectElement>("#sort-by")!;

  const render = () => {
    const sortBy = sortSel.value;
    const venues = Array.from(byVenue.keys());
    if (sortBy === "venue") {
      venues.sort();
    } else {
      const course = parseInt(sortBy, 10);
      venues.sort((a, b) => {
        const av = byVenue.get(a)!.find((x) => x.entry_course === course)?.win_rate ?? -1;
        const bv = byVenue.get(b)!.find((x) => x.entry_course === course)?.win_rate ?? -1;
        return bv - av;
      });
    }

    listEl.innerHTML = venues
      .map((v) => {
        const courseRows = byVenue.get(v)!;
        const bars = [1, 2, 3, 4, 5, 6].map((course) => {
          const r = courseRows.find((x) => x.entry_course === course);
          const rate = r?.win_rate ?? null;
          return {
            label: `${course}C`,
            value: rate != null ? rate * 100 : null,
            color: rate != null ? colorForWinRate(rate) : undefined,
          };
        });
        return `
          <div class="card">
            <div style="font-size:13px;margin-bottom:4px;">${venueName(v)}</div>
            ${renderBarChart(bars, { maxValue: MAX_RATE * 100, valueFormat: (v) => `${v.toFixed(1)}%` })}
          </div>
        `;
      })
      .join("");
  };

  sortSel.addEventListener("change", render);
  render();
}

function colorForWinRate(rate: number): string {
  // 1コース(highest, often ~0.5-0.6) -> green, 6コース(lowest, often <0.05) -> red.
  const t = Math.max(0, Math.min(1, rate / MAX_RATE));
  const hue = t * 140; // 0=red .. 140=green
  return `hsl(${hue}, 60%, 45%)`;
}
