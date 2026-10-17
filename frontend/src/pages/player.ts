import { renderShell, loading } from "../components/shell";
import { navigate, getQueryParams } from "../lib/router";
import { venueName, PERIOD_PRESETS, dateMonthsAgo, todayYYMMDD } from "../lib/constants";
import { renderTrendChart } from "../components/trendChart";
import {
  getRacerProfile, getRacerNameHistory, getRacerVenueCourseGrid, getRacerMonthlyTrend,
  getRacerVenueMonthlyTrend, getRacerSummary, getVenueAffinity, getSeasonAffinity,
  getWeatherAffinity, getHeadToHead, getMotorStats, getUpcomingRaces,
} from "../lib/queries";

type Tab = "summary" | "trend" | "grid" | "affinity" | "h2h" | "motor" | "upcoming";

export async function renderPlayerPage(params: { torokuNo: string }) {
  const { torokuNo } = params;
  const content = renderShell({ title: `選手 #${torokuNo}`, back: true });
  loading(content);

  const profile = await getRacerProfile(torokuNo);
  if (!profile) {
    content.innerHTML = `<div class="empty">選手が見つかりません</div>`;
    return;
  }

  const initialTab = (getQueryParams().get("tab") as Tab) || "summary";

  content.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline;">
        <h2 style="margin:0;font-size:20px;">${profile.name_kanji}</h2>
        <span class="badge">${profile.klass}</span>
      </div>
      <dl class="profile-grid" style="margin-top:10px;">
        <dt>登録番号</dt><dd>${profile.toroku_no}</dd>
        <dt>支部</dt><dd>${profile.branch}</dd>
        <dt>生年月日</dt><dd>${profile.birth_date ?? "-"}</dd>
        <dt>性別</dt><dd>${profile.sex}</dd>
        <dt>登録期</dt><dd>${profile.training_period}期</dd>
        <dt>出身地</dt><dd>${profile.hometown}</dd>
      </dl>
      <div id="name-history"></div>
    </div>

    <div class="tabs" id="tabs">
      <button data-tab="summary">成績サマリ</button>
      <button data-tab="trend">傾向グラフ</button>
      <button data-tab="grid">場×コース</button>
      <button data-tab="affinity">相性</button>
      <button data-tab="h2h">対戦成績</button>
      <button data-tab="motor">モーター</button>
      <button data-tab="upcoming">出走予定</button>
    </div>
    <div id="tab-content"></div>
  `;

  // name change history (only show if there's more than one entry)
  getRacerNameHistory(torokuNo).then((hist) => {
    if (hist.length <= 1) return;
    const el = content.querySelector("#name-history")!;
    el.innerHTML = `
      <details style="margin-top:8px;font-size:12px;color:var(--text-dim);">
        <summary>氏名・級別の履歴（${hist.length}件）</summary>
        ${hist
          .map((h) => `<div style="padding:4px 0;">${h.year}年${h.period}期: ${h.name_kanji} / ${h.klass} / ${h.branch}</div>`)
          .join("")}
      </details>
    `;
  });

  const tabContent = content.querySelector<HTMLElement>("#tab-content")!;
  const tabsEl = content.querySelector<HTMLElement>("#tabs")!;

  const setActive = (tab: Tab) => {
    tabsEl.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  };

  const renderers: Record<Tab, () => Promise<void>> = {
    summary: () => renderSummaryTab(tabContent, torokuNo),
    trend: () => renderTrendTab(tabContent, torokuNo),
    grid: () => renderGridTab(tabContent, torokuNo),
    affinity: () => renderAffinityTab(tabContent, torokuNo),
    h2h: () => renderH2HTab(tabContent, torokuNo),
    motor: () => renderMotorTab(tabContent, torokuNo),
    upcoming: () => renderUpcomingTab(tabContent, torokuNo),
  };

  const activate = async (tab: Tab) => {
    setActive(tab);
    loading(tabContent);
    await renderers[tab]();
  };

  tabsEl.querySelectorAll<HTMLButtonElement>("button").forEach((b) => {
    b.addEventListener("click", () => activate(b.dataset.tab as Tab));
  });

  await activate(initialTab);
}

async function renderSummaryTab(el: HTMLElement, torokuNo: string) {
  el.innerHTML = `
    <div class="chip-row" id="period-chips">
      ${PERIOD_PRESETS.map((p, i) => `<span class="chip${i === 2 ? " active" : ""}" data-months="${p.months ?? ""}">${p.label}</span>`).join("")}
    </div>
    <div id="summary-body"><div class="loading">読み込み中…</div></div>
    <a href="#/player/${torokuNo}/history" style="display:block;text-align:center;margin-top:12px;">全出走履歴を見る →</a>
  `;
  const body = el.querySelector<HTMLElement>("#summary-body")!;

  const load = async (months: number | null) => {
    const summary = await getRacerSummary(torokuNo, months != null ? dateMonthsAgo(months) : undefined);
    body.innerHTML = `
      <div class="card">
        <div class="stat-row"><span class="label">出走数</span><span class="value">${summary.starts_valid}（例外 ${summary.starts_exception}）</span></div>
        <div class="stat-row"><span class="label">平均着順</span><span class="value">${fmt(summary.avg_finish)}</span></div>
        <div class="stat-row"><span class="label">1着率</span><span class="value">${pct(summary.win_rate)}</span></div>
        <div class="stat-row"><span class="label">2連対率</span><span class="value">${pct(summary.place2_rate)}</span></div>
        <div class="stat-row"><span class="label">3連対率</span><span class="value">${pct(summary.place3_rate)}</span></div>
        <div class="stat-row"><span class="label">平均ST</span><span class="value">${fmt(summary.avg_st, 2)}</span></div>
      </div>
    `;
  };

  el.querySelectorAll<HTMLElement>("#period-chips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      el.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      load(chip.dataset.months ? parseInt(chip.dataset.months, 10) : null);
    });
  });

  await load(12);
}

async function renderTrendTab(el: HTMLElement, torokuNo: string) {
  el.innerHTML = `
    <div class="field">
      <label for="trend-dim">集計軸</label>
      <select id="trend-dim">
        <option value="course">コース別</option>
        <option value="venue">場別</option>
      </select>
    </div>
    <div class="field" id="trend-sub"></div>
    <div class="card"><div id="trend-chart"><div class="loading">読み込み中…</div></div></div>
  `;
  const dimSel = el.querySelector<HTMLSelectElement>("#trend-dim")!;
  const subEl = el.querySelector<HTMLElement>("#trend-sub")!;
  const chartEl = el.querySelector<HTMLElement>("#trend-chart")!;

  const renderCourseSub = () => {
    subEl.innerHTML = `
      <label for="trend-course">コース</label>
      <select id="trend-course">
        <option value="">全コース</option>
        ${[1, 2, 3, 4, 5, 6].map((c) => `<option value="${c}">${c}コース</option>`).join("")}
      </select>
    `;
    subEl.querySelector("select")!.addEventListener("change", loadCourse);
  };
  const renderVenueSub = () => {
    subEl.innerHTML = `
      <label for="trend-venue">場</label>
      <select id="trend-venue">
        ${Array.from({ length: 24 }, (_, i) => String(i + 1).padStart(2, "0"))
          .map((c) => `<option value="${c}">${venueName(c)}</option>`)
          .join("")}
      </select>
    `;
    subEl.querySelector("select")!.addEventListener("change", loadVenue);
  };

  const loadCourse = async () => {
    const course = subEl.querySelector<HTMLSelectElement>("#trend-course")!.value;
    const data = await getRacerMonthlyTrend(torokuNo, course ? parseInt(course, 10) : undefined);
    chartEl.innerHTML = renderTrendChart(data.map((d) => ({ label: d.year_month, value: d.avg_finish })), { invert: false });
  };
  const loadVenue = async () => {
    const venue = subEl.querySelector<HTMLSelectElement>("#trend-venue")!.value;
    const data = await getRacerVenueMonthlyTrend(torokuNo, venue);
    chartEl.innerHTML = renderTrendChart(data.map((d) => ({ label: d.year_month, value: d.avg_finish })), { invert: false });
  };

  dimSel.addEventListener("change", () => {
    if (dimSel.value === "course") { renderCourseSub(); loadCourse(); }
    else { renderVenueSub(); loadVenue(); }
  });

  renderCourseSub();
  await loadCourse();
}

async function renderGridTab(el: HTMLElement, torokuNo: string) {
  const cells = await getRacerVenueCourseGrid(torokuNo);
  const byVenue = new Map<string, typeof cells>();
  for (const c of cells) {
    if (!byVenue.has(c.venue_code)) byVenue.set(c.venue_code, []);
    byVenue.get(c.venue_code)!.push(c);
  }
  const venues = Array.from(byVenue.keys()).sort();
  el.innerHTML = `
    <p style="font-size:12px;color:var(--text-dim);">色が濃いほど平均着順が良い（緑=好成績、赤=苦手）。タップで出走履歴へ。数字はコース番号。</p>
    ${venues
      .map((v) => {
        const rows = byVenue.get(v)!;
        const cellsHtml = [1, 2, 3, 4, 5, 6]
          .map((course) => {
            const r = rows.find((x) => x.entry_course === course);
            if (!r || r.starts_valid === 0) return `<div class="grid-cell empty">${course}</div>`;
            const color = colorForFinish(r.avg_finish_raw ?? 6);
            return `<div class="grid-cell" data-venue="${v}" data-course="${course}" style="background:${color}">
              ${fmt(r.avg_finish_raw, 1)}<span class="n">${course}C / ${r.starts_valid}走</span>
            </div>`;
          })
          .join("");
        return `<div class="card"><div style="font-size:13px;margin-bottom:6px;">${venueName(v)}</div><div class="grid-course">${cellsHtml}</div></div>`;
      })
      .join("")}
  `;
  el.querySelectorAll<HTMLElement>("[data-venue]").forEach((cell) => {
    cell.addEventListener("click", () => {
      navigate(`/player/${torokuNo}/history?venue=${cell.dataset.venue}&course=${cell.dataset.course}`);
    });
  });
}

async function renderAffinityTab(el: HTMLElement, torokuNo: string) {
  el.innerHTML = `<div class="loading">読み込み中…</div>`;
  const [venues, seasons, weathers] = await Promise.all([
    getVenueAffinity(torokuNo),
    getSeasonAffinity(torokuNo),
    getWeatherAffinity(torokuNo),
  ]);
  const topN = <T,>(arr: T[], n: number) => arr.slice(0, n);
  const renderVenueList = (rows: typeof venues, label: string) => `
    <div class="card">
      <div style="font-size:13px;margin-bottom:6px;">${label}</div>
      ${rows
        .map((r) => `<div class="stat-row"><span class="label">${venueName(r.venue_code)}</span><span class="value">${fmt(r.avg_finish, 2)} (${r.starts}走)</span></div>`)
        .join("") || "<div class='empty'>データなし</div>"}
    </div>
  `;
  el.innerHTML = `
    ${renderVenueList(topN(venues, 3), "得意な場 TOP3")}
    ${renderVenueList(topN([...venues].reverse(), 3), "苦手な場 TOP3")}
    <div class="card">
      <div style="font-size:13px;margin-bottom:6px;">季節別成績</div>
      ${seasons.map((s) => `<div class="stat-row"><span class="label">${s.season}</span><span class="value">${fmt(s.avg_finish, 2)} (${s.starts}走)</span></div>`).join("")}
    </div>
    <div class="card">
      <div style="font-size:13px;margin-bottom:6px;">天候別成績</div>
      ${weathers.map((w) => `<div class="stat-row"><span class="label">${w.weather}</span><span class="value">${fmt(w.avg_finish, 2)} (${w.starts}走)</span></div>`).join("")}
    </div>
  `;
}

async function renderH2HTab(el: HTMLElement, torokuNo: string) {
  el.innerHTML = `
    <div class="field">
      <label for="opp">対戦相手の登録番号</label>
      <input id="opp" inputmode="numeric" placeholder="例: 4004" />
    </div>
    <button class="primary" id="h2h-go" style="width:100%;">対戦成績を見る</button>
    <div id="h2h-result" style="margin-top:12px;"></div>
  `;
  el.querySelector("#h2h-go")!.addEventListener("click", async () => {
    const opp = el.querySelector<HTMLInputElement>("#opp")!.value.trim();
    if (!opp) return;
    const resultEl = el.querySelector<HTMLElement>("#h2h-result")!;
    loading(resultEl);
    const h2h = await getHeadToHead(torokuNo, opp);
    resultEl.innerHTML = `
      <div class="card">
        <div style="text-align:center;font-size:18px;margin-bottom:8px;">${h2h.wins}勝 ${h2h.losses}敗 ${h2h.ties}分</div>
        ${h2h.races
          .slice(0, 30)
          .map((r) => `<div class="stat-row"><span class="label">${r.date} ${venueName(r.venue_code)} ${r.race_no}R</span><span class="value">${r.my_finish ?? "-"} vs ${r.opp_finish ?? "-"}</span></div>`)
          .join("") || "<div class='empty'>対戦履歴がありません</div>"}
      </div>
    `;
  });
}

async function renderMotorTab(el: HTMLElement, torokuNo: string) {
  const rows = await getMotorStats(torokuNo);
  el.innerHTML = `
    <div class="table-scroll"><table>
      <thead><tr><th>場</th><th>モーター</th><th>出走</th><th>平均着順</th><th>1着率</th></tr></thead>
      <tbody>
        ${rows
          .map((r) => `<tr><td>${venueName(r.venue_code)}</td><td>${r.motor_no}</td><td>${r.starts}</td><td>${fmt(r.avg_finish, 2)}</td><td>${pct(r.win_rate)}</td></tr>`)
          .join("")}
      </tbody>
    </table></div>
    ${rows.length === 0 ? "<div class='empty'>データがありません</div>" : ""}
  `;
}

async function renderUpcomingTab(el: HTMLElement, torokuNo: string) {
  const rows = await getUpcomingRaces(torokuNo, todayYYMMDD());
  el.innerHTML = rows.length
    ? `<div class="card">${rows
        .map((r) => `<div class="list-item"><div>${r.date} ${venueName(r.venue_code)} ${r.race_no}R</div><div>${r.frame}号艇</div></div>`)
        .join("")}</div>`
    : `<div class="empty">出走予定のレースはありません</div>`;
}

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null || Number.isNaN(v) ? "-" : v.toFixed(digits);
}
function pct(v: number | null | undefined): string {
  return v == null || Number.isNaN(v) ? "-" : `${(v * 100).toFixed(1)}%`;
}
function colorForFinish(avg: number): string {
  // 1 (best) -> green, 6 (worst) -> red, via HSL interpolation
  const t = Math.max(0, Math.min(1, (avg - 1) / 5));
  const hue = 140 - t * 140; // 140=green .. 0=red
  return `hsl(${hue}, 60%, 45%)`;
}
