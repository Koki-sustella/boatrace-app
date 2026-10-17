import { renderShell, loading } from "../components/shell";
import { getQueryParams } from "../lib/router";
import { getRaceHistory, type RaceHistoryRow } from "../lib/queries";
import { venueName, GRADE_ORDER, EXCEPTION_LABELS, formatDate } from "../lib/constants";

export async function renderHistoryPage(params: { torokuNo: string }) {
  const { torokuNo } = params;
  const qp = getQueryParams();
  const content = renderShell({ title: "全出走履歴", back: true });

  content.innerHTML = `
    <div class="filter-toggle">
      <span style="font-size:12px;color:var(--text-dim)">絞り込み</span>
      <button id="toggle-filters" style="font-size:12px;padding:4px 10px;">条件 ▾</button>
    </div>
    <div id="filters" class="card" style="display:none;">
      <div class="row">
        <div class="field">
          <label for="f-venue">場</label>
          <select id="f-venue">
            <option value="">すべて</option>
            ${Array.from({ length: 24 }, (_, i) => String(i + 1).padStart(2, "0"))
              .map((c) => `<option value="${c}">${venueName(c)}</option>`)
              .join("")}
          </select>
        </div>
        <div class="field">
          <label for="f-course">進入コース</label>
          <select id="f-course">
            <option value="">すべて</option>
            ${[1, 2, 3, 4, 5, 6].map((c) => `<option value="${c}">${c}コース</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="row">
        <div class="field">
          <label for="f-grade">グレード</label>
          <select id="f-grade">
            <option value="">すべて</option>
            ${GRADE_ORDER.map((g) => `<option value="${g}">${g}</option>`).join("")}
          </select>
        </div>
        <div class="field">
          <label for="f-finish">着順</label>
          <select id="f-finish">
            <option value="">すべて</option>
            ${[1, 2, 3, 4, 5, 6].map((n) => `<option value="0${n}">${n}着</option>`).join("")}
            <option value="exception">例外（F・欠場等）</option>
          </select>
        </div>
      </div>
      <div class="row">
        <div class="field">
          <label for="f-from">期間（から）</label>
          <input id="f-from" type="date" />
        </div>
        <div class="field">
          <label for="f-to">期間（まで）</label>
          <input id="f-to" type="date" />
        </div>
      </div>
      <div class="field">
        <label for="f-order">並び替え</label>
        <select id="f-order">
          <option value="date_desc">新しい順</option>
          <option value="date_asc">古い順</option>
        </select>
      </div>
      <button class="primary" id="apply-filters" style="width:100%;">適用</button>
    </div>
    <div id="summary-line" style="font-size:12px;color:var(--text-dim);margin-bottom:8px;"></div>
    <button id="csv-export" style="margin-bottom:12px;">CSVダウンロード</button>
    <div id="rows"><div class="loading">読み込み中…</div></div>
  `;

  // pre-fill from query params (e.g. navigated from the venue×course grid)
  if (qp.get("venue")) content.querySelector<HTMLSelectElement>("#f-venue")!.value = qp.get("venue")!;
  if (qp.get("course")) content.querySelector<HTMLSelectElement>("#f-course")!.value = qp.get("course")!;
  if (qp.get("venue") || qp.get("course")) {
    content.querySelector<HTMLElement>("#filters")!.style.display = "block";
  }

  content.querySelector("#toggle-filters")!.addEventListener("click", () => {
    const f = content.querySelector<HTMLElement>("#filters")!;
    f.style.display = f.style.display === "none" ? "block" : "none";
  });

  let currentRows: RaceHistoryRow[] = [];

  const toYYMMDD = (iso: string) => {
    const [y, m, d] = iso.split("-");
    return `${y.slice(2)}${m}${d}`;
  };

  const load = async () => {
    const rowsEl = content.querySelector<HTMLElement>("#rows")!;
    loading(rowsEl);
    const fromIso = content.querySelector<HTMLInputElement>("#f-from")!.value;
    const toIso = content.querySelector<HTMLInputElement>("#f-to")!.value;
    const rows = await getRaceHistory({
      torokuNo,
      venueCode: content.querySelector<HTMLSelectElement>("#f-venue")!.value || undefined,
      entryCourse: content.querySelector<HTMLSelectElement>("#f-course")!.value
        ? parseInt(content.querySelector<HTMLSelectElement>("#f-course")!.value, 10)
        : undefined,
      grade: content.querySelector<HTMLSelectElement>("#f-grade")!.value || undefined,
      finish: content.querySelector<HTMLSelectElement>("#f-finish")!.value || undefined,
      fromDate: fromIso ? toYYMMDD(fromIso) : undefined,
      toDate: toIso ? toYYMMDD(toIso) : undefined,
      orderBy: content.querySelector<HTMLSelectElement>("#f-order")!.value as "date_desc" | "date_asc",
    });
    currentRows = rows;
    content.querySelector("#summary-line")!.textContent = `${rows.length}件`;
    renderRows(rowsEl, rows);
  };

  content.querySelector("#apply-filters")!.addEventListener("click", load);
  content.querySelector("#csv-export")!.addEventListener("click", () => exportCsv(currentRows, torokuNo));

  await load();
}

function renderRows(el: HTMLElement, rows: RaceHistoryRow[]) {
  if (!rows.length) {
    el.innerHTML = `<div class="empty">該当するレースがありません</div>`;
    return;
  }
  el.innerHTML = `
    <div class="table-scroll"><table>
      <thead><tr>
        <th>日付</th><th>場</th><th>R</th><th>G</th><th>進入</th><th>着</th><th>ST</th><th>天候</th>
      </tr></thead>
      <tbody>
        ${rows
          .map(
            (r) => `<tr>
              <td>${formatDate(r.date)}</td>
              <td>${venueName(r.venue_code)}</td>
              <td>${r.race_no}</td>
              <td>${gradeAbbrev(r.grade)}</td>
              <td>${r.entry_course ?? "-"}</td>
              <td>${r.exception_label ?? r.finish ?? "-"}</td>
              <td>${r.start_timing != null ? r.start_timing.toFixed(2) : "-"}</td>
              <td>${r.weather || "-"}</td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table></div>
  `;
}

function gradeAbbrev(g: string): string {
  const map: Record<string, string> = {
    SG: "SG", G1: "G1", G2: "G2", G3: "G3",
    オールレディース: "AL", ヴィーナスシリーズ: "VN", ルーキーシリーズ: "RK", マスターズリーグ: "ML", 一般: "一般",
  };
  return map[g] ?? g;
}

function exportCsv(rows: RaceHistoryRow[], torokuNo: string) {
  const header = ["日付", "場", "レース", "グレード", "レース名", "進入コース", "着順", "ST", "レースタイム秒", "天候", "風速", "波高"];
  const lines = [header.join(",")];
  for (const r of rows) {
    lines.push(
      [
        formatDate(r.date), venueName(r.venue_code), r.race_no, r.grade,
        csvEscape(r.title), r.entry_course ?? "", r.exception_label ?? r.finish ?? "",
        r.start_timing ?? "", r.race_time_sec ?? "", r.weather, r.wind_speed_m, r.wave_cm,
      ].join(",")
    );
  }
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `racer_${torokuNo}_history.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvEscape(s: string): string {
  if (s == null) return "";
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
