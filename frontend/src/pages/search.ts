import { renderShell, loading } from "../components/shell";
import { searchRacers, type RacerSearchResult } from "../lib/queries";
import { navigate } from "../lib/router";

export async function renderSearchPage() {
  const content = renderShell({ title: "選手検索", activeNav: "search" });
  content.innerHTML = `
    <div class="field">
      <label for="kw">登録番号・氏名（現在/旧姓）</label>
      <input id="kw" type="search" inputmode="search" placeholder="例: 4918 / 池 / 道上" />
    </div>
    <div class="filter-toggle">
      <span style="font-size:12px;color:var(--text-dim)">絞り込み</span>
      <button id="toggle-filters" style="font-size:12px;padding:4px 10px;">条件を開く ▾</button>
    </div>
    <div id="filters" style="display:none;">
      <div class="row">
        <div class="field">
          <label for="klass">級別</label>
          <select id="klass">
            <option value="">指定なし</option>
            <option>A1</option><option>A2</option><option>B1</option><option>B2</option>
          </select>
        </div>
        <div class="field">
          <label for="training">登録期</label>
          <input id="training" type="number" inputmode="numeric" placeholder="例: 100" />
        </div>
      </div>
      <div class="field">
        <label for="branch">支部</label>
        <input id="branch" placeholder="例: 東京" />
      </div>
    </div>
    <button class="primary" id="go" style="width:100%;margin-bottom:16px;">検索</button>
    <div id="results"></div>
  `;

  content.querySelector("#toggle-filters")!.addEventListener("click", (e) => {
    const f = content.querySelector<HTMLElement>("#filters")!;
    const btn = e.currentTarget as HTMLButtonElement;
    const open = f.style.display !== "none";
    f.style.display = open ? "none" : "block";
    btn.textContent = open ? "条件を開く ▾" : "条件を閉じる ▴";
  });

  const run = async () => {
    const results = content.querySelector<HTMLElement>("#results")!;
    loading(results);
    const keyword = (content.querySelector<HTMLInputElement>("#kw")!.value || "").trim();
    const klass = content.querySelector<HTMLSelectElement>("#klass")!.value;
    const branch = content.querySelector<HTMLInputElement>("#branch")!.value.trim();
    const trainingStr = content.querySelector<HTMLInputElement>("#training")!.value.trim();
    try {
      const rows = await searchRacers({
        keyword: keyword || undefined,
        klass: klass || undefined,
        branch: branch || undefined,
        trainingPeriod: trainingStr ? parseInt(trainingStr, 10) : undefined,
      });
      renderResults(results, rows);
    } catch (err) {
      results.innerHTML = `<div class="empty">検索エラー: ${(err as Error).message}</div>`;
    }
  };

  content.querySelector("#go")!.addEventListener("click", run);
  content.querySelector("#kw")!.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter") run();
  });
}

function renderResults(el: HTMLElement, rows: RacerSearchResult[]) {
  if (!rows.length) {
    el.innerHTML = `<div class="empty">該当する選手が見つかりません</div>`;
    return;
  }
  el.innerHTML = `<div class="card">${rows
    .map(
      (r) => `
      <div class="list-item" data-id="${r.toroku_no}" style="cursor:pointer;">
        <div>
          <div>${r.name_kanji} <span class="badge">${r.klass}</span></div>
          <div style="font-size:12px;color:var(--text-dim)">登番 ${r.toroku_no} ・ ${r.branch} ・ ${r.training_period}期</div>
        </div>
        <div>›</div>
      </div>`
    )
    .join("")}</div>`;
  el.querySelectorAll<HTMLElement>("[data-id]").forEach((item) => {
    item.addEventListener("click", () => navigate(`/player/${item.dataset.id}`));
  });
}
