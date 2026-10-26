import { renderShell, loading } from "../components/shell";
import { navigate } from "../lib/router";
import { venueName, formatDate } from "../lib/constants";
import {
  getRacerProfile, getRecentStarts, getRacerCourseAvgST,
  type RacerProfile, type RecentStartRow, type CourseAvgSTRow,
} from "../lib/queries";

const SLOTS = [1, 2, 3, 4, 5, 6];

export async function renderRaceComparePage() {
  const content = renderShell({ title: "直前比較", activeNav: "race-compare" });
  content.innerHTML = `
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:10px;">
      1〜6号艇の登録番号を入力すると、各艇の枠番コースでの平均ST・直近10走をまとめて表示します。
    </p>
    <div id="slot-inputs"></div>
    <button class="primary" id="go" style="width:100%;margin:8px 0 16px;">表示</button>
    <div id="results"></div>
  `;

  const inputsEl = content.querySelector<HTMLElement>("#slot-inputs")!;
  inputsEl.innerHTML = `
    <div class="slot-input-grid">
      ${SLOTS.map(
        (s) => `
        <div class="field">
          <label for="slot-${s}">${s}号艇</label>
          <input id="slot-${s}" inputmode="numeric" placeholder="登録番号" />
        </div>`
      ).join("")}
    </div>
  `;

  // Enter key on any slot input triggers the same lookup as the button.
  inputsEl.querySelectorAll<HTMLInputElement>("input").forEach((input) => {
    input.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") run();
    });
  });

  const resultsEl = content.querySelector<HTMLElement>("#results")!;

  const run = async () => {
    const slotIds = SLOTS.map((s) => ({
      slot: s,
      torokuNo: content.querySelector<HTMLInputElement>(`#slot-${s}`)!.value.trim(),
    })).filter((x) => x.torokuNo);

    if (!slotIds.length) {
      resultsEl.innerHTML = `<div class="empty">登録番号を入力してください</div>`;
      return;
    }

    loading(resultsEl);
    const results = await Promise.all(
      slotIds.map(async ({ slot, torokuNo }) => {
        const [profile, avgSt, recent] = await Promise.all([
          getRacerProfile(torokuNo),
          getRacerCourseAvgST(torokuNo, slot),
          getRecentStarts(torokuNo, 10),
        ]);
        return { slot, torokuNo, profile, avgSt, recent };
      })
    );
    renderResults(resultsEl, results);
  };

  content.querySelector("#go")!.addEventListener("click", run);
}

interface SlotResult {
  slot: number;
  torokuNo: string;
  profile: RacerProfile | null;
  avgSt: CourseAvgSTRow;
  recent: RecentStartRow[];
}

function renderResults(el: HTMLElement, results: SlotResult[]) {
  el.innerHTML = `
    <div class="compare-grid">
      ${results.map(renderSlotCard).join("")}
    </div>
  `;
  el.querySelectorAll<HTMLElement>("[data-goto]").forEach((link) => {
    link.addEventListener("click", () => navigate(`/player/${link.dataset.goto}`));
  });
}

function renderSlotCard(r: SlotResult): string {
  if (!r.profile) {
    return `<div class="card"><div class="badge">${r.slot}号艇</div><div class="empty">登録番号 ${r.torokuNo} の選手が見つかりません</div></div>`;
  }
  const p = r.profile;
  const stText = r.avgSt.starts > 0 ? `${r.avgSt.avg_st!.toFixed(2)}（${r.avgSt.starts}走）` : "データなし";

  const rows = r.recent
    .map((row) => {
      const finishDisplay = row.exception_label ?? row.finish ?? "-";
      return `<tr>
        <td>${formatDate(row.date)}</td>
        <td>${venueName(row.venue_code)}</td>
        <td>${row.entry_course ?? "-"}</td>
        <td>${finishDisplay}</td>
        <td>${row.start_timing != null ? row.start_timing.toFixed(2) : "-"}</td>
      </tr>`;
    })
    .join("");

  return `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
        <div>
          <span class="badge" style="margin-right:6px;">${r.slot}号艇</span>
          <span data-goto="${p.toroku_no}" style="font-weight:600;cursor:pointer;color:var(--accent);">${p.name_kanji}</span>
          <span class="badge">${p.klass}</span>
        </div>
      </div>
      <div class="stat-row">
        <span class="label">${r.slot}コース平均ST</span>
        <span class="value">${stText}</span>
      </div>
      <div class="table-scroll" style="margin-top:8px;">
        <table>
          <thead><tr><th>日付</th><th>場</th><th>進入</th><th>着</th><th>ST</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5" class="empty">出走履歴がありません</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}
