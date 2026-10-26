import { query, escapeSqlString } from "./db";
import { dateMonthsAgo } from "./constants";

export interface RacerSearchResult {
  toroku_no: string;
  name_kanji: string;
  klass: string;
  branch: string;
  training_period: number;
}

export async function searchRacers(opts: {
  keyword?: string;
  branch?: string;
  klass?: string;
  trainingPeriod?: number;
}): Promise<RacerSearchResult[]> {
  const conds: string[] = [];
  const kw = opts.keyword?.trim();
  if (kw) {
    if (/^\d+$/.test(kw)) {
      conds.push(`rc.toroku_no LIKE '${escapeSqlString(kw)}%'`);
    } else {
      const norm = escapeSqlString(kw.replace(/[\s　]/g, ""));
      conds.push(`
        rc.toroku_no IN (
          SELECT toroku_no FROM racer_history
          WHERE REPLACE(REPLACE(name_kanji, ' ', ''), '　', '') LIKE '%${norm}%'
        )
      `);
    }
  }
  if (opts.branch) conds.push(`rc.branch = '${escapeSqlString(opts.branch)}'`);
  if (opts.klass) conds.push(`rc.klass = '${escapeSqlString(opts.klass)}'`);
  if (opts.trainingPeriod != null) conds.push(`r.training_period = ${opts.trainingPeriod}`);

  const where = conds.length ? `WHERE ${conds.join(" AND ")}` : "";
  return query<RacerSearchResult>(`
    SELECT rc.toroku_no, REPLACE(REPLACE(rc.name_kanji, '　', ''), ' ', '') AS name_kanji,
           rc.klass, rc.branch, r.training_period
    FROM racer_current rc
    JOIN racers r USING (toroku_no)
    ${where}
    ORDER BY rc.toroku_no
    LIMIT 100
  `);
}

export interface RacerProfile {
  toroku_no: string;
  birth_date: string;
  sex: string;
  training_period: number;
  hometown: string;
  name_kanji: string;
  klass: string;
  branch: string;
}

export async function getRacerProfile(torokuNo: string): Promise<RacerProfile | null> {
  const rows = await query<RacerProfile>(`
    SELECT r.toroku_no, r.birth_date, r.sex, r.training_period, REPLACE(r.hometown, '　', '') AS hometown,
           REPLACE(REPLACE(rc.name_kanji, '　', ''), ' ', '') AS name_kanji, rc.klass, rc.branch
    FROM racers r JOIN racer_current rc USING (toroku_no)
    WHERE r.toroku_no = '${escapeSqlString(torokuNo)}'
  `);
  return rows[0] ?? null;
}

export interface RacerHistoryRow {
  year: number;
  period: number;
  name_kanji: string;
  klass: string;
  branch: string;
  calc_from: string;
  calc_to: string;
}

export async function getRacerNameHistory(torokuNo: string): Promise<RacerHistoryRow[]> {
  return query<RacerHistoryRow>(`
    SELECT year, period, REPLACE(REPLACE(name_kanji, '　', ''), ' ', '') AS name_kanji,
           klass, branch, calc_from, calc_to
    FROM racer_history
    WHERE toroku_no = '${escapeSqlString(torokuNo)}'
    ORDER BY year, period
  `);
}

export interface VenueCourseCell {
  venue_code: string;
  entry_course: number;
  starts_valid: number;
  starts_exception: number;
  avg_finish_raw: number | null;
  avg_finish_adjusted: number | null;
  win_rate: number | null;
  place2_rate: number | null;
  place3_rate: number | null;
  avg_finish_vs_baseline: number | null;
}

export async function getRacerVenueCourseGrid(torokuNo: string): Promise<VenueCourseCell[]> {
  return query<VenueCourseCell>(`
    SELECT venue_code, entry_course, starts_valid, starts_exception,
           avg_finish_raw, avg_finish_adjusted, win_rate, place2_rate, place3_rate,
           avg_finish_vs_baseline
    FROM agg_racer_venue_course
    WHERE toroku_no = '${escapeSqlString(torokuNo)}'
  `);
}

export interface MonthlyTrendPoint {
  year_month: string;
  avg_finish: number | null;
  starts: number;
}

export async function getRacerMonthlyTrend(torokuNo: string, entryCourse?: number): Promise<MonthlyTrendPoint[]> {
  const courseCond = entryCourse != null ? `AND entry_course = ${entryCourse}` : "";
  return query<MonthlyTrendPoint>(`
    SELECT year_month, sum(sum_finish) / NULLIF(sum(starts_valid), 0) AS avg_finish,
           sum(starts_valid) AS starts
    FROM agg_racer_course_month
    WHERE toroku_no = '${escapeSqlString(torokuNo)}' ${courseCond}
    GROUP BY year_month
    ORDER BY year_month
  `);
}

export interface RaceHistoryFilters {
  torokuNo: string;
  fromDate?: string; // YYMMDD
  toDate?: string;
  venueCode?: string;
  entryCourse?: number;
  grade?: string;
  finish?: string;
  orderBy?: "date_desc" | "date_asc";
}

export interface RaceHistoryRow {
  date: string;
  venue_code: string;
  race_no: number;
  title: string;
  grade: string;
  finish: string | null;
  exception_label: string | null;
  frame: number;
  entry_course: number | null;
  start_timing: number | null;
  race_time_sec: number | null;
  weather: string;
  wind_speed_m: number;
  wave_cm: number;
}

export async function getRaceHistory(f: RaceHistoryFilters): Promise<RaceHistoryRow[]> {
  const conds = [`reg_no = '${escapeSqlString(f.torokuNo)}'`];
  if (f.fromDate) conds.push(`date >= '${escapeSqlString(f.fromDate)}'`);
  if (f.toDate) conds.push(`date <= '${escapeSqlString(f.toDate)}'`);
  if (f.venueCode) conds.push(`venue_code = '${escapeSqlString(f.venueCode)}'`);
  if (f.entryCourse != null) conds.push(`entry_course = ${f.entryCourse}`);
  if (f.grade) conds.push(`grade = '${escapeSqlString(f.grade)}'`);
  if (f.finish) {
    conds.push(
      f.finish === "exception"
        ? "is_exception"
        : `finish = '${escapeSqlString(f.finish)}'`
    );
  }
  const order = f.orderBy === "date_asc" ? "date ASC, race_no ASC" : "date DESC, race_no DESC";
  return query<RaceHistoryRow>(`
    SELECT date, venue_code, race_no, title, grade, finish, exception_label,
           frame, entry_course, start_timing, race_time_sec, weather, wind_speed_m, wave_cm
    FROM entries_enriched
    WHERE ${conds.join(" AND ")}
    ORDER BY ${order}
    LIMIT 2000
  `);
}

export interface VenueCourseRankingRow {
  toroku_no: string;
  name_kanji: string;
  klass: string;
  starts: number;
  avg_finish: number;
  win_rate: number;
  place3_rate: number;
  avg_st: number | null;
  vs_baseline: number;
}

export async function getVenueCourseRanking(opts: {
  venueCode: string;
  entryCourse: number;
  periodMonths: number | null;
  grade?: string;
  minStarts: number;
  sortBy: "avg_finish" | "win_rate" | "place3_rate" | "starts";
}): Promise<VenueCourseRankingRow[]> {
  const conds = [`e.venue_code = '${escapeSqlString(opts.venueCode)}'`, `e.entry_course = ${opts.entryCourse}`];
  if (opts.periodMonths != null) conds.push(`e.date >= '${dateMonthsAgo(opts.periodMonths)}'`);
  if (opts.grade) conds.push(`e.grade = '${escapeSqlString(opts.grade)}'`);
  const sortCol = { avg_finish: "avg_finish ASC", win_rate: "win_rate DESC", place3_rate: "place3_rate DESC", starts: "starts DESC" }[opts.sortBy];

  const baseline = await query<{ avg_finish: number }>(`
    SELECT avg_finish FROM agg_venue_course_overall
    WHERE venue_code = '${escapeSqlString(opts.venueCode)}' AND entry_course = ${opts.entryCourse}
  `);
  const baselineAvg = baseline[0]?.avg_finish ?? null;

  const rows = await query<VenueCourseRankingRow>(`
    SELECT e.reg_no AS toroku_no, REPLACE(REPLACE(rc.name_kanji, '　', ''), ' ', '') AS name_kanji, rc.klass,
           count(*) FILTER (WHERE NOT e.is_exception) AS starts,
           avg(TRY_CAST(e.finish AS INTEGER)) FILTER (WHERE NOT e.is_exception) AS avg_finish,
           avg(CASE WHEN e.finish = '01' THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT e.is_exception) AS win_rate,
           avg(CASE WHEN TRY_CAST(e.finish AS INTEGER) <= 3 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT e.is_exception) AS place3_rate,
           avg(e.start_timing) AS avg_st
    FROM entries_enriched e
    JOIN racer_current rc ON rc.toroku_no = e.reg_no
    WHERE ${conds.join(" AND ")}
    GROUP BY 1, 2, 3
    HAVING count(*) FILTER (WHERE NOT e.is_exception) >= ${opts.minStarts}
    ORDER BY ${sortCol}
    LIMIT 200
  `);
  return rows.map((r) => ({ ...r, vs_baseline: baselineAvg != null ? r.avg_finish - baselineAvg : 0 }));
}

export interface GrowthRankingRow {
  toroku_no: string;
  name_kanji: string;
  entry_course: number;
  recent_avg: number;
  prior_avg: number;
  delta: number;
  recent_starts: number;
  starts_sg: number;
  starts_g1: number;
}

export async function getGrowthRanking(opts: {
  entryCourse?: number;
  recentMonths: number;
  minStarts: number;
  direction: "improving" | "declining";
}): Promise<GrowthRankingRow[]> {
  const recentFrom = dateMonthsAgoAsYearMonth(opts.recentMonths);
  const priorFrom = dateMonthsAgoAsYearMonth(opts.recentMonths * 2);
  const courseCond = opts.entryCourse != null ? `AND entry_course = ${opts.entryCourse}` : "";
  const order = opts.direction === "improving" ? "delta ASC" : "delta DESC";
  return query<GrowthRankingRow>(`
    WITH recent AS (
      SELECT toroku_no, entry_course,
             sum(sum_finish) / NULLIF(sum(starts_valid), 0) AS avg_finish,
             sum(starts_valid) AS starts,
             sum(starts_sg) AS starts_sg, sum(starts_g1) AS starts_g1
      FROM agg_racer_course_month
      WHERE year_month >= '${recentFrom}' ${courseCond}
      GROUP BY 1, 2
    ), prior AS (
      SELECT toroku_no, entry_course,
             sum(sum_finish) / NULLIF(sum(starts_valid), 0) AS avg_finish
      FROM agg_racer_course_month
      WHERE year_month >= '${priorFrom}' AND year_month < '${recentFrom}' ${courseCond}
      GROUP BY 1, 2
    )
    SELECT recent.toroku_no, REPLACE(REPLACE(rc.name_kanji, '　', ''), ' ', '') AS name_kanji,
           recent.entry_course, recent.avg_finish AS recent_avg, prior.avg_finish AS prior_avg,
           recent.avg_finish - prior.avg_finish AS delta, recent.starts AS recent_starts,
           recent.starts_sg, recent.starts_g1
    FROM recent
    JOIN prior USING (toroku_no, entry_course)
    JOIN racer_current rc ON rc.toroku_no = recent.toroku_no
    WHERE recent.starts >= ${opts.minStarts}
    ORDER BY ${order}
    LIMIT 100
  `);
}

function dateMonthsAgoAsYearMonth(months: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  const yy = String(d.getFullYear() % 100).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${yy}${mm}`;
}

export interface VenueMonthlyTrendPoint {
  year_month: string;
  avg_finish: number | null;
  starts: number;
}

export async function getRacerVenueMonthlyTrend(torokuNo: string, venueCode?: string): Promise<VenueMonthlyTrendPoint[]> {
  const venueCond = venueCode ? `AND venue_code = '${escapeSqlString(venueCode)}'` : "";
  return query<VenueMonthlyTrendPoint>(`
    SELECT substr(date, 1, 4) AS year_month,
           avg(TRY_CAST(finish AS INTEGER)) FILTER (WHERE NOT is_exception) AS avg_finish,
           count(*) FILTER (WHERE NOT is_exception) AS starts
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}' ${venueCond}
    GROUP BY 1
    ORDER BY 1
  `);
}

export interface RacerSummary {
  starts_valid: number;
  starts_exception: number;
  avg_finish: number | null;
  win_rate: number | null;
  place2_rate: number | null;
  place3_rate: number | null;
  avg_st: number | null;
}

export async function getRacerSummary(torokuNo: string, fromDate?: string): Promise<RacerSummary> {
  const dateCond = fromDate ? `AND date >= '${escapeSqlString(fromDate)}'` : "";
  const rows = await query<RacerSummary>(`
    SELECT
      count(*) FILTER (WHERE NOT is_exception) AS starts_valid,
      count(*) FILTER (WHERE is_exception) AS starts_exception,
      avg(TRY_CAST(finish AS INTEGER)) FILTER (WHERE NOT is_exception) AS avg_finish,
      avg(CASE WHEN finish = '01' THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS win_rate,
      avg(CASE WHEN TRY_CAST(finish AS INTEGER) <= 2 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place2_rate,
      avg(CASE WHEN TRY_CAST(finish AS INTEGER) <= 3 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place3_rate,
      avg(start_timing) AS avg_st
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}' ${dateCond}
  `);
  return rows[0];
}

export interface VenueAffinityRow {
  venue_code: string;
  starts: number;
  avg_finish: number;
  win_rate: number;
}

export async function getVenueAffinity(torokuNo: string): Promise<VenueAffinityRow[]> {
  return query<VenueAffinityRow>(`
    SELECT venue_code, sum(starts_valid) AS starts,
           sum(starts_valid * avg_finish_raw) / NULLIF(sum(starts_valid), 0) AS avg_finish,
           sum(starts_valid * win_rate) / NULLIF(sum(starts_valid), 0) AS win_rate
    FROM agg_racer_venue_course
    WHERE toroku_no = '${escapeSqlString(torokuNo)}'
    GROUP BY 1
    HAVING sum(starts_valid) > 0
    ORDER BY avg_finish ASC
  `);
}

export interface SeasonAffinityRow {
  season: string;
  starts: number;
  avg_finish: number | null;
}

export async function getSeasonAffinity(torokuNo: string): Promise<SeasonAffinityRow[]> {
  return query<SeasonAffinityRow>(`
    SELECT CASE
             WHEN CAST(substr(date, 3, 2) AS INTEGER) IN (3,4,5) THEN '春'
             WHEN CAST(substr(date, 3, 2) AS INTEGER) IN (6,7,8) THEN '夏'
             WHEN CAST(substr(date, 3, 2) AS INTEGER) IN (9,10,11) THEN '秋'
             ELSE '冬'
           END AS season,
           count(*) FILTER (WHERE NOT is_exception) AS starts,
           avg(TRY_CAST(finish AS INTEGER)) FILTER (WHERE NOT is_exception) AS avg_finish
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}'
    GROUP BY 1
    ORDER BY avg_finish ASC
  `);
}

export interface WeatherAffinityRow {
  weather: string;
  starts: number;
  avg_finish: number | null;
}

export async function getWeatherAffinity(torokuNo: string): Promise<WeatherAffinityRow[]> {
  return query<WeatherAffinityRow>(`
    SELECT weather, count(*) FILTER (WHERE NOT is_exception) AS starts,
           avg(TRY_CAST(finish AS INTEGER)) FILTER (WHERE NOT is_exception) AS avg_finish
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}'
    GROUP BY 1
    HAVING count(*) > 0
    ORDER BY avg_finish ASC
  `);
}

export interface HeadToHeadRace {
  date: string;
  venue_code: string;
  race_no: number;
  my_finish: string | null;
  opp_finish: string | null;
}

export interface HeadToHead {
  races: HeadToHeadRace[];
  wins: number;
  losses: number;
  ties: number;
}

export async function getHeadToHead(torokuNo: string, opponentNo: string): Promise<HeadToHead> {
  const races = await query<HeadToHeadRace>(`
    SELECT a.date, a.venue_code, a.race_no, a.finish AS my_finish, b.finish AS opp_finish
    FROM entries a
    JOIN entries b ON a.venue_code = b.venue_code AND a.date = b.date AND a.race_no = b.race_no
    WHERE a.reg_no = '${escapeSqlString(torokuNo)}' AND b.reg_no = '${escapeSqlString(opponentNo)}'
    ORDER BY a.date DESC
  `);
  let wins = 0, losses = 0, ties = 0;
  for (const r of races) {
    const a = r.my_finish ? parseInt(r.my_finish, 10) : null;
    const b = r.opp_finish ? parseInt(r.opp_finish, 10) : null;
    if (a == null || b == null) ties++;
    else if (a < b) wins++;
    else if (a > b) losses++;
    else ties++;
  }
  return { races, wins, losses, ties };
}

export interface MotorStatsRow {
  venue_code: string;
  motor_no: number;
  starts: number;
  avg_finish: number | null;
  win_rate: number | null;
}

export async function getMotorStats(torokuNo: string): Promise<MotorStatsRow[]> {
  return query<MotorStatsRow>(`
    SELECT venue_code, motor_no,
           count(*) FILTER (WHERE NOT is_exception) AS starts,
           avg(TRY_CAST(finish AS INTEGER)) FILTER (WHERE NOT is_exception) AS avg_finish,
           avg(CASE WHEN finish = '01' THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS win_rate,
           max(date) AS last_used
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}'
    GROUP BY 1, 2
    ORDER BY last_used DESC
  `);
}

export interface UpcomingRaceRow {
  date: string;
  venue_code: string;
  race_no: number;
  title: string;
  frame: number;
  klass: string;
}

export async function getUpcomingRaces(torokuNo: string, fromDate: string): Promise<UpcomingRaceRow[]> {
  return query<UpcomingRaceRow>(`
    SELECT date, venue_code, race_no, title, frame, klass
    FROM program_entries
    WHERE reg_no = '${escapeSqlString(torokuNo)}' AND date >= '${escapeSqlString(fromDate)}'
    ORDER BY date ASC, race_no ASC
    LIMIT 50
  `);
}

export interface RecentStartRow {
  date: string;
  venue_code: string;
  race_no: number;
  entry_course: number | null;
  finish: string | null;
  exception_label: string | null;
  start_timing: number | null;
  race_time_sec: number | null;
  grade: string;
}

export async function getRecentStarts(torokuNo: string, limit = 10, course?: number): Promise<RecentStartRow[]> {
  const courseCond = course != null ? `AND entry_course = ${course}` : "";
  return query<RecentStartRow>(`
    SELECT date, venue_code, race_no, entry_course, finish, exception_label, start_timing, race_time_sec, grade
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}' ${courseCond}
    ORDER BY date DESC, race_no DESC
    LIMIT ${limit}
  `);
}

export interface CourseAvgSTRow {
  avg_st: number | null;
  starts: number;
}

export async function getRacerCourseAvgST(torokuNo: string, course: number): Promise<CourseAvgSTRow> {
  const rows = await query<CourseAvgSTRow>(`
    SELECT avg(start_timing) AS avg_st, count(start_timing) AS starts
    FROM entries_enriched
    WHERE reg_no = '${escapeSqlString(torokuNo)}' AND entry_course = ${course}
  `);
  return rows[0] ?? { avg_st: null, starts: 0 };
}

export interface VenueCourseWinRateRow {
  venue_code: string;
  entry_course: number;
  win_rate: number | null;
  place2_rate: number | null;
  place3_rate: number | null;
  starts_valid: number;
}

export async function getAllVenueCourseWinRates(): Promise<VenueCourseWinRateRow[]> {
  return query<VenueCourseWinRateRow>(`
    SELECT venue_code, entry_course, win_rate, place2_rate, place3_rate, starts_valid
    FROM agg_venue_course_overall
    ORDER BY venue_code, entry_course
  `);
}
