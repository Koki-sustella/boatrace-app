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


def parse_k_file(text: str, source_date: str):
    races: list[RaceHeader] = []
    boats: list[BoatResult] = []
    unparsed_lines: list[str] = []

    for m in VENUE_BLOCK_RE.finditer(text):
        venue_code, block = m.group(1), m.group(2)
        lines = block.splitlines()
        current_race = None
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

    return races, boats, unparsed_lines
