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
      1〜6号艇の登録番号を入力すると、各艇の枠番コースでの平均STを一覧比較し、
      その号艇のコースに限定した直近10走を表示します。
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
          getRecentStarts(torokuNo, 10, slot),
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
    <div class="card">
      <div style="font-size:13px;margin-bottom:6px;font-weight:600;">コース別平均ST比較</div>
      ${renderStComparisonTable(results)}
      <div style="font-size:13px;margin:14px 0 6px;font-weight:600;">直近10走の1着回数比較</div>
      ${renderWinCountComparisonTable(results)}
    </div>
    <div class="compare-grid">
      ${results.map(renderSlotCard).join("")}
    </div>
  `;
  el.querySelectorAll<HTMLElement>("[data-goto]").forEach((link) => {
    link.addEventListener("click", () => navigate(`/player/${link.dataset.goto}`));
  });
}

function winCountInRecent(r: SlotResult): number {
  return r.recent.filter((row) => row.finish === "01").length;
}

function renderWinCountComparisonTable(results: SlotResult[]): string {
  const sorted = [...results].sort((a, b) => a.slot - b.slot);
  const rows = sorted
    .map((r) => {
      const name = r.profile ? r.profile.name_kanji : `(${r.torokuNo})`;
      return `<tr>
        <td><span class="badge">${r.slot}号艇</span></td>
        <td style="text-align:left;">${name}</td>
        <td><strong>${winCountInRecent(r)}</strong>回</td>
        <td>${r.recent.length}走中</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="table-scroll">
      <table>
        <thead><tr><th>枠</th><th style="text-align:left;">選手</th><th>1着回数</th><th>対象</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderStComparisonTable(results: SlotResult[]): string {
  const sorted = [...results].sort((a, b) => a.slot - b.slot);
  const rows = sorted
    .map((r) => {
      const name = r.profile ? r.profile.name_kanji : `(${r.torokuNo})`;
      const stText = r.avgSt.starts > 0 ? r.avgSt.avg_st!.toFixed(2) : "-";
      const startsText = r.avgSt.starts > 0 ? `${r.avgSt.starts}走` : "データなし";
      return `<tr>
        <td><span class="badge">${r.slot}号艇</span></td>
        <td style="text-align:left;">${name}</td>
        <td><strong>${stText}</strong></td>
        <td>${startsText}</td>
      </tr>`;
    })
    .join("");
  return `
    <div class="table-scroll">
      <table>
        <thead><tr><th>枠</th><th style="text-align:left;">選手</th><th>平均ST</th><th>出走数</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderSlotCard(r: SlotResult): string {
  if (!r.profile) {
    return `<div class="card"><div class="badge">${r.slot}号艇</div><div class="empty">登録番号 ${r.torokuNo} の選手が見つかりません</div></div>`;
  }
  const p = r.profile;

  const rows = r.recent
    .map((row) => {
      const finishDisplay = row.exception_label ?? row.finish ?? "-";
      const isTopGrade = row.grade === "SG" || row.grade === "G1";
      return `<tr${isTopGrade ? ' style="color:var(--warn);"' : ""}>
        <td>${isTopGrade ? "★ " : ""}${formatDate(row.date)}</td>
        <td>${venueName(row.venue_code)}</td>
        <td>${row.race_no}R</td>
        <td>${finishDisplay}</td>
        <td>${row.start_timing != null ? row.start_timing.toFixed(2) : "-"}</td>
      </tr>`;
    })
    .join("");

  const winCount = winCountInRecent(r);
  return `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
        <div>
          <span class="badge" style="margin-right:6px;">${r.slot}号艇</span>
          <span data-goto="${p.toroku_no}" style="font-weight:600;cursor:pointer;color:var(--accent);">${p.name_kanji}</span>
          <span class="badge">${p.klass}</span>
        </div>
        <div style="font-size:12px;color:var(--text-dim);white-space:nowrap;">1着 <strong style="color:var(--text);font-size:14px;">${winCount}</strong>/${r.recent.length}</div>
      </div>
      <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px;">${r.slot}コースでの直近10走（★=SG・G1）</div>
      <div class="table-scroll">
        <table>
          <thead><tr><th>日付</th><th>場</th><th>R</th><th>着</th><th>ST</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5" class="empty">${r.slot}コースでの出走履歴がありません</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}
