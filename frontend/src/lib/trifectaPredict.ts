/** 3連単予想モデル -- TypeScript twin of scripts/backtest_trifecta_sweep2.py.
 * Keep these two in sync: the backtest's reported hit rate is only
 * meaningful for this exact formula. See that script's docstring for the
 * full methodology writeup (priority weights, G1/SG weighting, Plackett-Luce
 * combination, the 枠番=進入コース assumption).
 */
import type { RecentStartRow, CourseAvgSTRow, CourseAptitudeRow, RacerLatestRatingRow } from "./queries";

const W_CA = 0.3;
const W_RF = 0.2;
const W_ST = 0.15;
const W_WR = 0.3;
const W_CL = 0.05;
const GRADE_WEIGHT = 2.0;
const FALLBACK_POINT = 3.5;
const FALLBACK_ST = 0.17;
const FALLBACK_WR = 4.5; // roughly a B1 league-average win_rate
const FALLBACK_CL = 2.0; // roughly B1
const STRENGTH_SCALE = 4.0;

const CLASS_SCORE: Record<string, number> = { A1: 4.0, A2: 3.0, B1: 2.0, B2: 1.0 };

export interface BoatInput {
  frame: number; // 1-6, the bet-able 艇番
  recent: RecentStartRow[]; // already course-filtered, most recent first
  avgSt: CourseAvgSTRow;
  aptitude: CourseAptitudeRow;
  rating: RacerLatestRatingRow;
}

function finishPoint(finish: string | null, isException: boolean): number {
  if (isException || finish == null) return 0;
  const f = parseInt(finish, 10);
  if (!(f >= 1 && f <= 6)) return 0;
  return 7 - f;
}

function recentFormScore(recent: RecentStartRow[]): number {
  if (!recent.length) return FALLBACK_POINT;
  let wsum = 0;
  let wtot = 0;
  for (const row of recent) {
    const w = row.grade === "SG" || row.grade === "G1" ? GRADE_WEIGHT : 1.0;
    wsum += finishPoint(row.finish, row.exception_label != null) * w;
    wtot += w;
  }
  return wtot > 0 ? wsum / wtot : FALLBACK_POINT;
}

function winRateScore(rating: RacerLatestRatingRow): number {
  const nat = rating.national_win_rate;
  const loc = rating.local_win_rate;
  if (nat == null && loc == null) return FALLBACK_WR;
  if (nat == null) return loc!;
  if (loc == null) return nat;
  return (nat + loc) / 2;
}

function classScore(rating: RacerLatestRatingRow): number {
  if (rating.klass == null) return FALLBACK_CL;
  return CLASS_SCORE[rating.klass] ?? FALLBACK_CL;
}

function normalize(values: number[]): number[] {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (hi - lo < 1e-9) return values.map(() => 0.5);
  return values.map((v) => (v - lo) / (hi - lo));
}

export interface TrifectaPick {
  combo: [number, number, number]; // [1着, 2着, 3着] by 艇番
  probability: number;
}

export function predictTrifecta(boats: BoatInput[], topN = 12): TrifectaPick[] {
  const rf = boats.map((b) => recentFormScore(b.recent));
  const stRaw = boats.map((b) => (b.avgSt.starts > 0 ? -b.avgSt.avg_st! : -FALLBACK_ST));
  const ca = boats.map((b) => (b.aptitude.starts > 0 ? b.aptitude.avg_point! : FALLBACK_POINT));
  const wr = boats.map((b) => winRateScore(b.rating));
  const cl = boats.map((b) => classScore(b.rating));

  const rfN = normalize(rf);
  const stN = normalize(stRaw);
  const caN = normalize(ca);
  const wrN = normalize(wr);
  const clN = normalize(cl);

  const strength = new Map<number, number>();
  boats.forEach((b, i) => {
    const composite = W_CA * caN[i] + W_RF * rfN[i] + W_ST * stN[i] + W_WR * wrN[i] + W_CL * clN[i];
    strength.set(b.frame, Math.exp(STRENGTH_SCALE * composite));
  });

  const frames = boats.map((b) => b.frame);
  const total = Array.from(strength.values()).reduce((a, b) => a + b, 0);

  const results: TrifectaPick[] = [];
  for (const a of frames) {
    for (const b of frames) {
      if (b === a) continue;
      for (const c of frames) {
        if (c === a || c === b) continue;
        const pa = strength.get(a)! / total;
        const rem1 = total - strength.get(a)!;
        const pb = rem1 > 0 ? strength.get(b)! / rem1 : 0;
        const rem2 = rem1 - strength.get(b)!;
        const pc = rem2 > 0 ? strength.get(c)! / rem2 : 0;
        results.push({ combo: [a, b, c], probability: pa * pb * pc });
      }
    }
  }

  results.sort((x, y) => y.probability - x.probability);
  return results.slice(0, topN);
}

export interface BoatScoreBreakdown {
  frame: number;
  rf: number;
  st: number | null;
  ca: number;
  wr: number | null;
  cl: string | null;
}

export function scoreBreakdown(boats: BoatInput[]): BoatScoreBreakdown[] {
  return boats.map((b) => ({
    frame: b.frame,
    rf: recentFormScore(b.recent),
    st: b.avgSt.starts > 0 ? b.avgSt.avg_st! : null,
    ca: b.aptitude.starts > 0 ? b.aptitude.avg_point! : FALLBACK_POINT,
    wr: b.rating.national_win_rate != null || b.rating.local_win_rate != null ? winRateScore(b.rating) : null,
    cl: b.rating.klass,
  }));
}
