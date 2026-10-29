"""Phase 1 prototype parser for the official K-file (競走成績データ).

Layout confirmed empirically against real downloaded sample files (see
docs/derive_offsets_output.txt and docs/file_format_research.md) rather than
trusted blindly from third-party write-ups. The leading finish/frame/reg_no/name
columns are genuinely fixed-width (confirmed via derive_offsets.py against a
real line) -- a loose whitespace-based regex there false-positive-matches
payout lines like "複勝     3         1250  2 ..." (複勝/3/1250 happen to look
like finish/frame/reg_no). The later numeric columns (motor/boat/exhibition/
course/ST/race_time) are NOT reliably fixed-width (gaps vary, exception rows
substitute placeholders), so those are parsed via token extraction instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VENUE_BLOCK_RE = re.compile(r"(\d{2})KBGN\n(.*?)\n\1KEND", re.S)
RACE_HEADER_RE = re.compile(
    r"^\s*(?P<rno>\d{1,2})R\s+(?P<title>\S.*?)\s{2,}H(?P<dist>\d+)m\s+"
    r"(?P<weather>\S+?)\s+風\s+(?P<winddir>\S+?)\s+(?P<windspeed>\d+)m\s+"
    r"波\s+(?P<wave>\d+)cm\s*$"
)
# Fixed-width: 2 leading spaces, finish(2), 2 spaces, frame(1), 1 space, reg_no(4), 1 space, name(8), rest.
BOAT_LINE_RE = re.compile(r"^  (?P<finish>..)  (?P<frame>\d) (?P<regno>\d{4}) (?P<name>.{8})(?P<rest>.*)$")
VALID_FINISH_RE = re.compile(r"^(0[0-6]|F.?|L[01_]?|K[01_]?|S[012_]?|[転沈不妨落エ失]\s?)$")

# Payout section (within a race block, after its boat rows). Confirmed against
# real files (see docs/derive_offsets_output.txt): one row per 単勝/複勝/２連単/
# ２連複/３連単/３連複, three rows for 拡連複 (its three top-3 pairs) -- the
# label is blank on 拡連複's 2nd/3rd continuation rows. Two special cases also
# confirmed in real data: "特払い" (flat consolation payout, no combo -- seen
# when too many boats are scratched/flying for a normal payout) and "不成立"
# (that bet type alone is void -- seen when there aren't enough valid finishers
# for it, even while other bet types in the same race paid out normally).
PAYOUT_BET_TYPES = {
    "単勝": "win", "複勝": "place", "２連単": "exacta2", "２連複": "quinella2",
    "拡連複": "wide", "３連単": "exacta3", "３連複": "trio",
}
PAYOUT_LABEL_RE = re.compile(
    "^\\s*(?P<label>" + "|".join(PAYOUT_BET_TYPES) + ")?\\s*(?P<rest>.*)$"
)
PAYOUT_COMBO_AMOUNT_RE = re.compile(r"(?P<combo>\d(?:-\d){0,2})\s+(?P<amount>\d+)")
PAYOUT_NINKI_RE = re.compile(r"人気\s*(?P<ninki>\d+)")
PAYOUT_SPECIAL_RE = re.compile(r"特払い\s+(?P<amount>\d+)")

EXCEPTION_FINISH_CODES = {
    "F": "フライング",
    "L0": "出遅れ(責任外)", "L1": "出遅れ(責任)", "L": "出遅れ",
    "K0": "欠場(責任外)", "K1": "欠場(責任)", "K": "欠場",
    "S0": "失格(責任外)", "S1": "失格(責任)", "S2": "妨害失格",
    "転": "転覆失格", "沈": "沈没失格", "不": "不完走失格", "妨": "妨害失格",
    "落": "落水失格", "エ": "エンスト失格", "失": "失格(その他)",
    # 他艇の大量フライング等でレース自体が無効(不成立)になった際、フライングしなかった
    # 艇に付く着順コード。実データで確認: 直後に単独行で「レース不成立」と明記される。
    "00": "レース不成立",
}


@dataclass
class RaceHeader:
    venue_code: str
    date: str
    race_no: int
    title: str
    distance_m: int
    weather: str
    wind_dir: str
    wind_speed_m: int
    wave_cm: int


@dataclass
class BoatResult:
    venue_code: str
    date: str
    race_no: int
    finish: str | None  # None if exception; numeric rows get "01".."06" as int string
    is_exception: bool
    exception_label: str | None
    frame: int
    reg_no: str
    name: str
    motor_no: int | None
    boat_no: int | None
    exhibition_time: float | None
    entry_course: int | None
    start_timing: float | None
    start_is_flying: bool
    race_time_sec: float | None


@dataclass
class PayoutRow:
    venue_code: str
    date: str
    race_no: int
    bet_type: str  # win/place/exacta2/quinella2/wide/exacta3/trio
    combo: str | None  # e.g. "6-2-5", or a single frame "6" for win/place; None if void
    amount: int | None  # yen per 100-yen bet; None if void
    ninki: int | None  # popularity rank; not reported for win/place
    is_void: bool  # 不成立: this bet type alone had no valid payout for this race
    is_special_payout: bool  # 特払い: flat consolation payout, no combo


def _clean_name(raw: str) -> str:
    return raw.replace("　", "").strip()


def _parse_rest_tokens(rest: str):
    """Parse the free-form remainder of a boat line: motor, boat, exhibition,
    course, ST, race_time. Handles K./F-prefixed/placeholder variants."""
    tokens = rest.split()
    motor_no = boat_no = entry_course = None
    exhibition_time = start_timing = race_time_sec = None
    start_is_flying = False

    def to_int(tok):
        try:
            return int(tok)
        except ValueError:
            return None

    def to_float(tok):
        try:
            return float(tok)
        except ValueError:
            return None

    i = 0
    # motor number
    if i < len(tokens) and tokens[i].isdigit():
        motor_no = to_int(tokens[i]); i += 1
    # boat number
    if i < len(tokens) and tokens[i].isdigit():
        boat_no = to_int(tokens[i]); i += 1
    # exhibition time: normal "6.86" or "K" "." placeholder pair
    if i < len(tokens):
        if tokens[i] == "K" and i + 1 < len(tokens) and tokens[i + 1] == ".":
            i += 2  # absent: no exhibition time
        else:
            exhibition_time = to_float(tokens[i]); i += 1
    # entry course: normal digit or "K" "." placeholder pair
    if i < len(tokens):
        if tokens[i] == "K" and i + 1 < len(tokens) and tokens[i + 1] == ".":
            i += 2
        elif tokens[i].isdigit():
            entry_course = to_int(tokens[i]); i += 1
    # ST (start timing): "0.23", "F0.02" (flying), or ".", "." placeholder pair
    if i < len(tokens):
        tok = tokens[i]
        if tok == "." :
            i += 1
            if i < len(tokens) and tokens[i] == ".":
                i += 1
        elif tok.startswith("F"):
            start_is_flying = True
            start_timing = to_float(tok[1:]); i += 1
        else:
            start_timing = to_float(tok); i += 1
    # race time: "1.51.8" (M.SS.d) or ".", "." placeholder pair
    if i < len(tokens):
        tok = tokens[i]
        if tok == ".":
            i += 1
            if i < len(tokens) and tokens[i] == ".":
                i += 1
        else:
            m = re.match(r"^(\d)\.(\d{2})\.(\d)$", tok)
            if m:
                minutes, secs, tenths = m.groups()
                race_time_sec = int(minutes) * 60 + int(secs) + int(tenths) / 10

    return motor_no, boat_no, exhibition_time, entry_course, start_timing, start_is_flying, race_time_sec


def _parse_payout_line(line: str, venue_code: str, source_date: str, race_no: int, current_bet_type: str | None):
    """Try to interpret `line` as one payout row for the current race. Returns
    (PayoutRow | None, next_bet_type) -- next_bet_type carries forward so a
    blank-label continuation row (拡連複's 2nd/3rd row) is attributed correctly."""
    lm = PAYOUT_LABEL_RE.match(line)
    label, rest = lm.group("label"), lm.group("rest")
    bet_type = PAYOUT_BET_TYPES[label] if label else current_bet_type
    if bet_type is None or not rest.strip():
        return None, current_bet_type

    if "不成立" in rest:
        return PayoutRow(
            venue_code=venue_code, date=source_date, race_no=race_no, bet_type=bet_type,
            combo=None, amount=None, ninki=None, is_void=True, is_special_payout=False,
        ), bet_type

    sm = PAYOUT_SPECIAL_RE.search(rest)
    if sm:
        return PayoutRow(
            venue_code=venue_code, date=source_date, race_no=race_no, bet_type=bet_type,
            combo=None, amount=int(sm.group("amount")), ninki=None, is_void=False, is_special_payout=True,
        ), bet_type

    pairs = PAYOUT_COMBO_AMOUNT_RE.findall(rest)
    if not pairs:
        return None, bet_type
    nm = PAYOUT_NINKI_RE.search(rest)
    ninki = int(nm.group("ninki")) if nm else None
    # Only win/place ever carry >1 pair per line, and neither reports a 人気.
    combo, amount = pairs[0]
    return PayoutRow(
        venue_code=venue_code, date=source_date, race_no=race_no, bet_type=bet_type,
        combo=combo, amount=int(amount), ninki=ninki, is_void=False, is_special_payout=False,
    ), bet_type


def parse_k_file(text: str, source_date: str):
    races: list[RaceHeader] = []
    boats: list[BoatResult] = []
    payouts: list[PayoutRow] = []
    unparsed_lines: list[str] = []

    for m in VENUE_BLOCK_RE.finditer(text):
        venue_code, block = m.group(1), m.group(2)
        lines = block.splitlines()
        current_race = None
        current_bet_type = None
        for line in lines:
            hm = RACE_HEADER_RE.match(line)
            if hm:
                current_race = RaceHeader(
                    venue_code=venue_code,
                    date=source_date,
                    race_no=int(hm.group("rno")),
                    title=hm.group("title").replace("　", "").strip(),
                    distance_m=int(hm.group("dist")),
                    weather=hm.group("weather"),
                    wind_dir=hm.group("winddir"),
                    wind_speed_m=int(hm.group("windspeed")),
                    wave_cm=int(hm.group("wave")),
                )
                races.append(current_race)
                current_bet_type = None
                continue
            bm = BOAT_LINE_RE.match(line)
            if bm and current_race is not None:
                finish_raw = bm.group("finish")
                if not VALID_FINISH_RE.match(finish_raw):
                    continue  # not a real boat line (e.g. a payout line that happened to line up)
                finish_key = finish_raw.strip()
                is_exception = finish_key in EXCEPTION_FINISH_CODES or not finish_key.isdigit()
                (motor_no, boat_no, exhibition_time, entry_course,
                 start_timing, start_is_flying, race_time_sec) = _parse_rest_tokens(bm.group("rest"))
                boats.append(BoatResult(
                    venue_code=venue_code,
                    date=source_date,
                    race_no=current_race.race_no,
                    finish=None if is_exception else finish_key,
                    is_exception=is_exception,
                    exception_label=EXCEPTION_FINISH_CODES.get(finish_key) if is_exception else None,
                    frame=int(bm.group("frame")),
                    reg_no=bm.group("regno"),
                    name=_clean_name(bm.group("name")),
                    motor_no=motor_no,
                    boat_no=boat_no,
                    exhibition_time=exhibition_time,
                    entry_course=entry_course,
                    start_timing=start_timing,
                    start_is_flying=start_is_flying,
                    race_time_sec=race_time_sec,
                ))
                continue
            if current_race is not None and line.strip():
                payout, current_bet_type = _parse_payout_line(
                    line, venue_code, source_date, current_race.race_no, current_bet_type
                )
                if payout:
                    payouts.append(payout)

    return races, boats, payouts, unparsed_lines
