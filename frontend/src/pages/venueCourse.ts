import { renderShell, loading } from "../components/shell";
import { navigate } from "../lib/router";
import { venueName, GRADE_ORDER, PERIOD_PRESETS } from "../lib/constants";
import { getVenueCourseRanking, type VenueCourseRankingRow } from "../lib/queries";

export async function renderVenueCoursePage() {
  const content = renderShell({ title: "場×コース検索", activeNav: "venue-course" });
  content.innerHTML = `
    <div class="row">
      <div class="field">
        <label for="venue">場</label>
        <select id="venue">
          ${Array.from({ length: 24 }, (_, i) => String(i + 1).padStart(2, "0"))
            .map((c) => `<option value="${c}">${venueName(c)}</option>`)
            .join("")}
        </select>
      </div>
      <div class="field">
        <label for="course">コース</label>
        <select id="course">
          ${[1, 2, 3, 4, 5, 6].map((c) => `<option value="${c}">${c}コース</option>`).join("")}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="field">
        <label for="period">期間</label>
        <select id="period">
          ${PERIOD_PRESETS.map((p, i) => `<option value="${p.months ?? ""}" ${i === 2 ? "selected" : ""}>${p.label}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="grade">グレード</label>
        <select id="grade">
          <option value="">すべて</option>
          ${GRADE_ORDER.map((g) => `<option value="${g}">${g}</option>`).join("")}
        </select>
      </div>
    </div>
    <div class="row">
      <div class="field">
        <label for="min-starts">最低出走数</label>
        <input id="min-starts" type="number" value="5" inputmode="numeric" />
      </div>
      <div class="field">
        <label for="sort">並び替え</label>
        <select id="sort">
          <option value="avg_finish">平均着順</option>
          <option value="win_rate">1着率</option>
          <option value="place3_rate">3連対率</option>
          <option value="starts">出走数</option>
        </select>
      </div>
    </div>
    <button class="primary" id="go" style="width:100%;margin-bottom:12px;">検索</button>
    <div id="results"><div class="empty">条件を指定して検索してください</div></div>
  `;

  const run = async () => {
    const results = content.querySelector<HTMLElement>("#results")!;
    loading(results);
    const periodVal = content.querySelector<HTMLSelectElement>("#period")!.value;
    const rows = await getVenueCourseRanking({
      venueCode: content.querySelector<HTMLSelectElement>("#venue")!.value,
      entryCourse: parseInt(content.querySelector<HTMLSelectElement>("#course")!.value, 10),
      periodMonths: periodVal ? parseInt(periodVal, 10) : null,
      grade: content.querySelector<HTMLSelectElement>("#grade")!.value || undefined,
      minStarts: parseInt(content.querySelector<HTMLInputElement>("#min-starts")!.value || "0", 10),
      sortBy: content.querySelector<HTMLSelectElement>("#sort")!.value as any,
    });
    renderResults(results, rows);
  };

  content.querySelector("#go")!.addEventListener("click", run);
}

function renderResults(el: HTMLElement, rows: VenueCourseRankingRow[]) {
  if (!rows.length) {
    el.innerHTML = `<div class="empty">該当する選手がいません</div>`;
    return;
  }
  el.innerHTML = `
    <div class="table-scroll"><table>
      <thead><tr><th>選手</th><th>出走</th><th>平均着順</th><th>1着率</th><th>3連対率</th><th>平均ST</th><th>対平均</th></tr></thead>
      <tbody>
        ${rows
          .map(
            (r) => `<tr data-id="${r.toroku_no}" style="cursor:pointer;">
              <td style="text-align:left;">${r.name_kanji}<span class="badge" style="margin-left:4px;">${r.klass}</span></td>
              <td>${r.starts}</td>
              <td>${r.avg_finish.toFixed(2)}</td>
              <td>${(r.win_rate * 100).toFixed(1)}%</td>
              <td>${(r.place3_rate * 100).toFixed(1)}%</td>
              <td>${r.avg_st != null ? r.avg_st.toFixed(2) : "-"}</td>
              <td style="color:${r.vs_baseline < 0 ? "var(--good)" : "var(--bad)"}">${r.vs_baseline > 0 ? "+" : ""}${r.vs_baseline.toFixed(2)}</td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table></div>
  `;
  el.querySelectorAll<HTMLElement>("[data-id]").forEach((row) => {
    row.addEventListener("click", () => navigate(`/player/${row.dataset.id}`));
  });
}
