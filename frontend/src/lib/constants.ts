export const VENUE_NAMES: Record<string, string> = {
  "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
  "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
  "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
  "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
  "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
  "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
};

export const VENUE_CODES = Object.keys(VENUE_NAMES);

export function venueName(code: string): string {
  return VENUE_NAMES[code] ?? code;
}

export const GRADE_ORDER = [
  "SG", "G1", "G2", "G3", "オールレディース", "ヴィーナスシリーズ",
  "ルーキーシリーズ", "マスターズリーグ", "一般",
];

export const GRADE_COLORS: Record<string, string> = {
  SG: "#f59e0b",
  G1: "#ef4444",
  G2: "#f97316",
  G3: "#eab308",
  オールレディース: "#ec4899",
  ヴィーナスシリーズ: "#d946ef",
  ルーキーシリーズ: "#22c55e",
  マスターズリーグ: "#06b6d4",
  一般: "#64748b",
};

export const EXCEPTION_LABELS = [
  "フライング", "出遅れ(責任)", "出遅れ(責任外)",
  "欠場(責任)", "欠場(責任外)", "失格(責任)", "失格(責任外)",
  "妨害失格", "転覆失格", "沈没失格", "不完走失格", "落水失格",
  "エンスト失格", "失格(その他)", "レース不成立",
];

export const PERIOD_PRESETS = [
  { label: "直近3か月", months: 3 },
  { label: "直近半年", months: 6 },
  { label: "直近1年", months: 12 },
  { label: "直近2年", months: 24 },
  { label: "全期間", months: null },
] as const;

/** 'YYMMDD' -> 'YYYY/MM/DD' for display. */
export function formatDate(yymmdd: string): string {
  const yy = parseInt(yymmdd.slice(0, 2), 10);
  const mm = yymmdd.slice(2, 4);
  const dd = yymmdd.slice(4, 6);
  return `20${String(yy).padStart(2, "0")}/${mm}/${dd}`;
}

/** 'YYMMDD' -> 'YYMMDD' N months earlier, for period-preset filtering. */
export function dateMonthsAgo(months: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  const yy = String(d.getFullYear() % 100).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yy}${mm}${dd}`;
}

export function todayYYMMDD(): string {
  return dateMonthsAgo(0);
}
