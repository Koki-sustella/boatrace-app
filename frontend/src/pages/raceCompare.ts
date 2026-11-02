import { renderShell, loading } from "../components/shell";
import { navigate } from "../lib/router";
import { venueName, formatDate, VENUE_CODES } from "../lib/constants";
import {
  getRacerProfilesBatch, getRecentStartsBatch, getCourseStatsBatch, getRacerLatestRatingsBatch,
  getRacerMeetPerformancesBatch, getVenueCourseWinRates, racerCourseKey,
  type RacerProfile, type RecentStartRow, type CourseAvgSTRow, type CourseAptitudeRow, type RacerLatestRatingRow,
  type MeetPerformanceRow,
} from "../lib/queries";
import { predictTrifecta, scoreBreakdown, type BoatInput } from "../lib/trifectaPredict";

const SLOTS = [1, 2, 3, 4, 5, 6];

// Module-level (survives SPA navigation away from and back to this page,
// since the module isn't re-evaluated -- only cleared by an explicit reset
// or a full page reload).
const lastSlotValues: Record<number, string> = {};
let lastVenue = "";
let lastResults: SlotResult[] | null = null;

export async function renderRaceComparePage() {
  const content = renderShell({ title: "直前比較", activeNav: "race-compare" });
  content.innerHTML = `
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:10px;">
      競艇場と1〜6号艇の登録番号を入力すると、各艇の枠番コースでの平均STを一覧比較し、
      その号艇のコースに限定した直近10走・3連単の買い目候補を表示します。
    </p>
    <div class="field">
      <label for="venue-select">競艇場</label>
      <select id="venue-select">
        <option value="">選択してください</option>
        ${VENUE_CODES.map((c) => `<option value="${c}" ${c === lastVenue ? "selected" : ""}>${venueName(c)}</option>`).join("")}
      </select>
    </div>
    <div id="slot-inputs"></div>
    <div style="display:flex;gap:8px;margin:8px 0 16px;">
      <button class="primary" id="go" style="flex:1;">表示</button>
      <button id="reset" style="flex:0 0 auto;">リセット</button>
    </div>
    <div id="results"></div>
  `;

  content.querySelector<HTMLSelectElement>("#venue-select")!.addEventListener("change", (e) => {
    lastVenue = (e.target as HTMLSelectElement).value;
  });

  const inputsEl = content.querySelector<HTMLElement>("#slot-inputs")!;
  inputsEl.innerHTML = `
    <div class="slot-input-grid">
      ${SLOTS.map(
        (s) => `
        <div class="field">
          <label for="slot-${s}">${s}号艇</label>
          <input id="slot-${s}" inputmode="numeric" placeholder="登録番号" value="${lastSlotValues[s] ?? ""}" />
        </div>`
      ).join("")}
    </div>
  `;

  const resultsEl = content.querySelector<HTMLElement>("#results")!;

  // Enter key on any slot input triggers the same lookup as the button;
  // any edit updates the persisted value so it survives tab switches.
  // Registration numbers are always 4 digits, so once an input reaches that
  // length, jump focus to the next slot automatically.
  const slotInputs = inputsEl.querySelectorAll<HTMLInputElement>("input");
  slotInputs.forEach((input, i) => {
    const slot = SLOTS[i];
    input.addEventListener("input", () => {
      lastSlotValues[slot] = input.value;
      if (input.value.length >= 4 && i < slotInputs.length - 1) {
        slotInputs[i + 1].focus();
      }
    });
    input.addEventListener("keydown", (e) => {
      if ((e as KeyboardEvent).key === "Enter") run();
    });
  });

  if (lastResults) {
    renderResults(resultsEl, lastResults, lastVenue);
  }

  const run = async () => {
    const venue = content.querySelector<HTMLSelectElement>("#venue-select")!.value;
    const slotIds = SLOTS.map((s) => ({
      slot: s,
      torokuNo: content.querySelector<HTMLInputElement>(`#slot-${s}`)!.value.trim(),
    })).filter((x) => x.torokuNo);

    if (!slotIds.length) {
      resultsEl.innerHTML = `<div class="empty">登録番号を入力してください</div>`;
      return;
    }

    loading(resultsEl);
    const torokuNos = slotIds.map((x) => x.torokuNo);
    const [profiles, courseStats, recentByKey, ratings, meets, venueCourseRows] = await Promise.all([
      getRacerProfilesBatch(torokuNos),
      getCourseStatsBatch(slotIds.map(({ slot, torokuNo }) => ({ torokuNo, course: slot }))),
      getRecentStartsBatch(slotIds.map(({ slot, torokuNo }) => ({ torokuNo, course: slot })), 10),
      getRacerLatestRatingsBatch(torokuNos),
      getRacerMeetPerformancesBatch(torokuNos),
      venue ? getVenueCourseWinRates(venue) : Promise.resolve([]),
    ]);
    const vcByCourse = new Map(venueCourseRows.map((r) => [r.entry_course, r.win_rate]));

    const results = slotIds.map(({ slot, torokuNo }) => {
      const key = racerCourseKey(torokuNo, slot);
      const stats = courseStats.get(key);
      return {
        slot,
        torokuNo,
        profile: profiles.get(torokuNo) ?? null,
        avgSt: stats?.avgSt ?? { avg_st: null, starts: 0 },
        recent: recentByKey.get(key) ?? [],
        aptitude: stats?.aptitude ?? { avg_point: null, starts: 0 },
        rating: ratings.get(torokuNo) ?? { national_win_rate: null, local_win_rate: null, klass: null, motor_2rentai_rate: null },
        meet: meets.get(torokuNo) ?? { avg_point: null, starts: 0 },
        vcWinRate: vcByCourse.get(slot) ?? null,
      };
    });
    lastResults = results;
    renderResults(resultsEl, results, venue);
  };

  const reset = () => {
    SLOTS.forEach((s) => {
      delete lastSlotValues[s];
      content.querySelector<HTMLInputElement>(`#slot-${s}`)!.value = "";
    });
    lastVenue = "";
    content.querySelector<HTMLSelectElement>("#venue-select")!.value = "";
    lastResults = null;
    resultsEl.innerHTML = "";
  };

  content.querySelector("#go")!.addEventListener("click", run);
  content.querySelector("#reset")!.addEventListener("click", reset);
}

interface SlotResult {
  slot: number;
  torokuNo: string;
  profile: RacerProfile | null;
  avgSt: CourseAvgSTRow;
  recent: RecentStartRow[];
  aptitude: CourseAptitudeRow;
  rating: RacerLatestRatingRow;
  meet: MeetPerformanceRow;
  vcWinRate: number | null;
}

function renderResults(el: HTMLElement, results: SlotResult[], venue: string) {
  const validResults = results.filter((r) => r.profile);
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
    ${renderTrifectaCard(validResults, venue)}
  `;
  el.querySelectorAll<HTMLElement>("[data-goto]").forEach((link) => {
    link.addEventListener("click", () => navigate(`/player/${link.dataset.goto}`));
  });
}

function renderTrifectaCard(results: SlotResult[], venue: string): string {
  if (results.length < 3) {
    return `
      <div class="card">
        <div style="font-size:13px;margin-bottom:6px;font-weight:600;">3連単 買い目候補</div>
        <div class="empty">3艇以上入力すると買い目候補を表示します</div>
      </div>
    `;
  }

  const boats: BoatInput[] = results.map((r) => ({
    frame: r.slot,
    recent: r.recent,
    avgSt: r.avgSt,
    aptitude: r.aptitude,
    rating: r.rating,
    meet: r.meet,
    vcWinRate: r.vcWinRate,
  }));
  const isWomensRace = results.every((r) => r.profile!.sex === "女");
  const picks = predictTrifecta(boats, 12, isWomensRace);
  const breakdown = scoreBreakdown(boats);
  const nameByFrame = new Map(results.map((r) => [r.slot, r.profile!.name_kanji]));

  const picksRows = picks
    .map(
      ({ combo, probability }, i) => `
      <tr>
        <td>${i + 1}</td>
        <td style="font-weight:600;">${combo.join("-")}</td>
        <td style="text-align:left;">${combo.map((f) => nameByFrame.get(f)).join(" / ")}</td>
        <td>${(probability * 100).toFixed(2)}%</td>
      </tr>`
    )
    .join("");

  const breakdownRows = breakdown
    .map(
      (b) => `
      <tr>
        <td><span class="badge">${b.frame}号艇</span></td>
        <td>${b.ca.toFixed(2)}</td>
        <td>${b.rf.toFixed(2)}</td>
        <td>${b.st != null ? b.st.toFixed(2) : "-"}</td>
        <td>${b.wr != null ? b.wr.toFixed(2) : "-"}</td>
        <td>${b.cl ?? "-"}</td>
        <td>${b.motor != null ? b.motor.toFixed(2) : "-"}</td>
        <td>${b.meet != null ? b.meet.toFixed(2) : "-"}</td>
        <td>${b.vc != null ? (b.vc * 100).toFixed(1) + "%" : "-"}</td>
      </tr>`
    )
    .join("");

  return `
    <div class="card">
      <div style="font-size:13px;margin-bottom:4px;font-weight:600;">各艇のスコア内訳${isWomensRace ? '<span class="badge" style="margin-left:6px;">女子レース用の重み</span>' : ""}</div>
      <p style="font-size:11px;color:var(--text-dim);margin:0 0 10px;">
        考慮要素: コース適性(全場・全期間) / 全国・当地勝率 / 直近10走(G1・SG重み2倍) / 平均ST / 級別 / モーター2連対率 / 節間成績 / 場×コース勝率。
        ${isWomensRace ? "出走6名が全員女性のため、女子レース専用の重み付けで算出しています。" : ""}
        ${!venue ? '<br><span style="color:var(--warn);">競艇場が未選択のため、場×コース勝率は反映されていません。</span>' : ""}
      </p>
      <div class="table-scroll">
        <table>
          <thead><tr><th>枠</th><th>コース適性★点</th><th>直近10走★点</th><th>平均ST</th><th>全国/当地勝率</th><th>級別</th><th>モーター2連対率</th><th>節間成績</th><th>場×コース勝率</th></tr></thead>
          <tbody>${breakdownRows}</tbody>
        </table>
      </div>
      <details style="margin-top:10px;font-size:12px;">
        <summary style="cursor:pointer;color:var(--text-dim);">3連単 買い目候補（上位${picks.length}点）を見る</summary>
        <p style="font-size:11px;color:var(--text-dim);margin:8px 0 10px;">
          統計的傾向に基づく参考情報であり、的中を保証するものではありません。
          枠番＝進入コースと仮定して算出しています。
        </p>
        <div class="table-scroll">
          <table>
            <thead><tr><th>順位</th><th>3連単</th><th style="text-align:left;">選手</th><th>推定確率</th></tr></thead>
            <tbody>${picksRows}</tbody>
          </table>
        </div>
      </details>
    </div>
  `;
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
