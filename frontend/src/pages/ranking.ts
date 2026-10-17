import { renderShell, loading } from "../components/shell";
import { navigate } from "../lib/router";
import { getGrowthRanking, type GrowthRankingRow } from "../lib/queries";

export async function renderRankingPage() {
  const content = renderShell({ title: "伸び率ランキング", activeNav: "ranking" });
  content.innerHTML = `
    <div class="row">
      <div class="field">
        <label for="course">コース</label>
        <select id="course">
          <option value="">全コース</option>
          ${[1, 2, 3, 4, 5, 6].map((c) => `<option value="${c}">${c}コース</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="direction">方向</label>
        <select id="direction">
          <option value="improving">伸びている順</option>
          <option value="declining">落ちている順</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div class="field">
        <label for="recent-months">直近の比較期間（か月）</label>
        <select id="recent-months">
          <option value="2">直近2か月 vs 前2か月</option>
          <option value="3" selected>直近3か月 vs 前3か月</option>
          <option value="6">直近6か月 vs 前6か月</option>
        </select>
      </div>
      <div class="field">
        <label for="min-starts">最低出走数（直近期間）</label>
        <input id="min-starts" type="number" value="5" inputmode="numeric" />
      </div>
    </div>
    <button class="primary" id="go" style="width:100%;margin-bottom:12px;">ランキングを見る</button>
    <p style="font-size:11px;color:var(--text-dim);">※ SG・G1戦の出走が多い選手は着順が不利に出やすいため、グレード別出走数を併記しています。</p>
    <div id="results"><div class="empty">条件を指定してください</div></div>
  `;

  const run = async () => {
    const results = content.querySelector<HTMLElement>("#results")!;
    loading(results);
    const courseVal = content.querySelector<HTMLSelectElement>("#course")!.value;
    const rows = await getGrowthRanking({
      entryCourse: courseVal ? parseInt(courseVal, 10) : undefined,
      recentMonths: parseInt(content.querySelector<HTMLSelectElement>("#recent-months")!.value, 10),
      minStarts: parseInt(content.querySelector<HTMLInputElement>("#min-starts")!.value || "0", 10),
      direction: content.querySelector<HTMLSelectElement>("#direction")!.value as "improving" | "declining",
    });
    renderResults(results, rows);
  };

  content.querySelector("#go")!.addEventListener("click", run);
}

function renderResults(el: HTMLElement, rows: GrowthRankingRow[]) {
  if (!rows.length) {
    el.innerHTML = `<div class="empty">該当する選手がいません</div>`;
    return;
  }
  el.innerHTML = `<div class="card">${rows
    .map(
      (r) => `
      <div class="list-item" data-id="${r.toroku_no}" style="cursor:pointer;">
        <div>
          <div>${r.name_kanji} <span class="badge">${r.entry_course}コース</span></div>
          <div style="font-size:11px;color:var(--text-dim);">
            直近 ${r.recent_avg.toFixed(2)} ← 以前 ${r.prior_avg.toFixed(2)}（${r.recent_starts}走, SG${r.starts_sg}/G1${r.starts_g1}）
          </div>
        </div>
        <div style="font-weight:700;color:${r.delta < 0 ? "var(--good)" : "var(--bad)"}">${r.delta > 0 ? "+" : ""}${r.delta.toFixed(2)}</div>
      </div>`
    )
    .join("")}</div>`;
  el.querySelectorAll<HTMLElement>("[data-id]").forEach((item) => {
    item.addEventListener("click", () => navigate(`/player/${item.dataset.id}`));
  });
}
