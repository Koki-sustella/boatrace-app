# ボートレース公式サイト K-file / B-file 固定長テキスト仕様（有志調査まとめ）

**Status: reverse-engineered from community sources, NOT official.** The official BOAT RACE site
(boatrace.jp / www1.mbrace.or.jp) does not publish a layout page for these two files — it only
publishes one for the fan file ("モーターボートファン手帳" / レーサー期別成績,
https://www.boatrace.jp/owpc/pc/extra/data/layout.html). Everything below was reconstructed from
third-party blog posts, Qiita/Zenn articles, and open-source parser code. Where sources disagreed
or a value could not be confirmed, that is called out explicitly rather than guessed. **Verify every
offset against real downloaded files before trusting it in production.**

---

## 0. Common facts (high confidence, corroborated by multiple independent sources)

- **Download URLs** (as given by the user, confirmed by multiple blogs/repos):
  - K-file (競走成績データ): `https://www1.mbrace.or.jp/od2/K/{YYYYMM}/k{YYMMDD}.lzh`
  - B-file (番組表データ): `https://www1.mbrace.or.jp/od2/B/{YYYYMM}/b{YYMMDD}.lzh`
- **Compression**: LZH (LHA, specifically LH5). Needs an LZH/LHA decompressor (`lhafile` in Python,
  `@kirinsaninc/lhats` in JS, etc.) — there is no native `.zip`/`.gz` support for this.
- **Character encoding**: Shift-JIS / CP932, confirmed by every source that mentioned it at all
  (koji30learn.com explicitly uses `encoding='shift-jis'` when opening the decompressed `.TXT`;
  a Zenn article independently confirms `cp932`). Expect old/extended-kanji ("gaiji") characters in
  racer names that don't round-trip cleanly through standard cp932 decoders — one source (Zenn,
  `zenn.dev/nishizumi_nobu`) explicitly complains about "古い漢字や謎のコードが入っていて手で消す
  必要がある" (old kanji / mystery codes that must be manually stripped).
- **Line endings**: CR/LF. This is explicitly stated for the related "PC-KYOTEI Database" normalized
  format (see §3), and is consistent with every Shift-JIS fixed-length Japanese government/industry
  text format of this era. Not independently re-confirmed against a raw sample byte-for-byte in this
  research pass — treat as high-confidence but unverified for the *raw* lzh contents specifically.
- **One file per day, all venues together**: both the K-file and B-file, once decompressed, are a
  single `.TXT` file covering all 24 venues racing that day (not one file per venue). Confirmed by
  cstenmt/boatrace's download+parse scripts and by multiple Qiita articles describing "一日分をまとめて
  ダウンロードできる".
- **File body markers**: at least one source (Yahoo! 知恵袋 thread + a Qiita summary) shows the file
  literally starts with a global marker and then per-venue markers, e.g.:
  ```
  STARTK
  23KBGN
    ... (唐津 block) ...
  23KEND
  24BBGN                  <- (this example mixed K/B refs; treat the exact prefix letter as per file type)
  ```
  For the B-file the per-venue markers are `{venue#}BBGN` ... `{venue#}BEND`; for the K-file they are
  `{venue#}KBGN` ... `{venue#}KEND`, with the whole file opening with `STARTK` / `STARTB` respectively.
  **Confidence: medium** — this came from a search-engine paraphrase of a blog post and a Yahoo!知恵袋
  answer, not a verbatim file dump I fetched directly. The *existence* of per-venue begin/end sentinel
  lines is corroborated by multiple sources: a Qiita article (Carl_Jonson) separately references
  `［成績］` and `---`-style separators within the venue block, and cstenmt's parser reads lines in a
  strict sequence (title line, then a date/venue line, then repeating per-race blocks) implying fixed
  sentinel structure rather than free-form blank-line separation. **Exact sentinel spelling/placement
  should be confirmed against a real file.**
- **Within a venue block**: a venue header (venue name + event title + day number), then one block per
  race (race header line with race number/title/distance/weather/wind/wave), then 6 per-boat result
  lines (K-file) or 6 per-boat entry lines (B-file), then (K-file only) a payout section per race.
- **Grade (SG/G1/G2/G3/一般) is NOT a separate coded field in the raw K-file/B-file race title line.**
  Every direct-parser source that touches the title field (cstenmt, denden56, tatsutatsu) treats it as
  free text ("レース名" / title string) and does not decode a grade byte from it. The one source that
  *does* have an explicit "グレードコード" value table (1=SG, 2=PG1, 3=G1, 4=G2, 5=G3, 9=一般) is the
  PC-KYOTEI PDF spec (§3), but that code is attached to the *"出走表(競艇場)" L1 record*, which per
  that same document is sourced from the **live website** (`boatrace.jp/owpc/pc/race/index`), not from
  the downloadable B-file/K-file. **Conclusion: in the K-file/B-file you almost certainly have to infer
  grade from the title text** (matching known SG/G1/G2/G3 event names, or cross-referencing the
  separate schedule page), exactly as the user suspected. This is the single most important "no direct
  field" finding of this research.

---

## 1. K-file (競走成績データ, race results)

### 1.1 Record structure

Per real-world parser code (cstenmt/boatrace, denden56-cloud/boatrace-papertrade,
tatsutatsu1028/-boatrace-ai), each race block inside a venue section looks like, in order:

1. **Venue header** (once per venue, appears before that venue's races) — contains venue name
   (full-width, e.g. `唐　津`), `［成績］` marker, date, event title, "第N日".
2. **Race header line** (once per race) — contains race number + "R", race title/class text,
   distance (`H????m` format), and weather/wind/wave as literal Japanese text, e.g. (raw sample,
   medium confidence — captured via a tool-assisted paraphrase of a Qiita article, not a verbatim
   byte dump):
   ```
   1R       一　　般　　                 H1800m  晴　  風  北　　 1m  波　  1cm
   ```
3. **6 per-boat result lines**, one per starting boat, e.g. (same caveat on exactness):
   ```
   01  1 4627 藤　原　　菜　希 63   76  6.72   1    0.09     1.50.0
   ```
4. **決まり手 (winning technique)** — appears associated with the race header/result block as a short
   literal text value (逃げ/差し/まくり/まくり差し/抜き/恵まれ), not a numeric code.
5. **Payout block** — one line per bet type, in the fixed order
   単勝(win) → 複勝(place) → ２連単(exacta) → ２連複(quinella) → 拡連複(wide) → ３連単(trifecta) →
   ３連複(trio), e.g. (Qiita, teruqii 払戻金 article — this one came through with better fidelity,
   treat as higher confidence):
   ```
   単勝     2         2770
   複勝     6          120
   ２連単   2-6      11130  人気    24
   ２連複   2-6       4920  人気    13
   拡連複   2-6        620  人気    11
            1-2        460  人気     7
            1-6        200  人気     2
   ３連単   2-6-1    36510  人気    86
   ３連複   1-2-6     1940  人気     8
   ```
   Notes confirmed by this source: 拡連複 (wide) legitimately has multiple winning combinations per
   race (shown as repeated unlabeled lines under one `拡連複` heading) because it pays out 3 combos;
   popularity rank (人気) is present for every multi-boat bet type but **not** for 単勝/複勝.
   複勝 is noted by the same author as sometimes showing only one winning boat's payout even though
   two boats place, a known real-world data-quality quirk to defend against.

### 1.2 Per-boat result line — field order and widths

Two independent sources gave concrete column positions for the per-boat result line. **They disagree
on exact byte offsets — order agrees, widths/offsets do not fully agree — so both are presented.**
Treat order as solid, exact offsets as unconfirmed until checked against a real file.

**Source A — cstenmt/boatrace `txtTocsv_results.py`** (direct Python slicing on the decompressed text;
`c` = the per-boat line, indices are Python 0-based *character* offsets after Shift-JIS decode, so one
full-width kanji = one index, same as one half-width char = one index):

| Order | Field (JP) | Field (EN) | Python slice | Width |
|---|---|---|---|---|
| 1 | 着順 | finish position | `c[2:4]` | 2 |
| 2 | 艇番 | frame/boat number | `c[6]` | 1 |
| 3 | 登録番号 | racer registration number | `c[8:12]` | 4 |
| 4 | 選手名 | racer name | `c[13:20]` | 7 |
| 5 | モーター番号 | motor number | `c[22:24]` | 2 |
| 6 | ボート番号 | boat number | `c[27:29]` | 2 |
| 7 | 展示タイム | exhibition time | `c[31:36]` | 5 |
| 8 | 進入コース | entry course | `c[38]` | 1 |
| 9 | ST（スタートタイミング） | start timing | `c[43:47]` | 4 |
| 10 | レースタイム | race time | `c[52:58]` | 6 |

**Source B — PC-KYOTEI "結果(艇番)" K3 record** (see §3 for the full table and the caveat that this is
a *reformatted* DB record with a 15/16-byte record-id+date+venue+race prefix baked in — offsets below
have that prefix subtracted for comparability, i.e. shown as "position within the per-boat record,
0-based, after stripping the 16-byte prefix that covers レコード種別ID+データ区分+開催年+開催月日+
競艇場コード+レースNo"):

| Order | Field (JP) | Field (EN) | Offset (0-based, prefix stripped) | Width |
|---|---|---|---|---|
| 1 | 艇番 | frame number | 0 | 1 |
| 2 | 登録番号 | racer reg. number | 1 | 4 |
| 3 | 氏名 | racer name | 5 | 16 |
| 4 | 着順 | finish position (coded, see §1.3) | 21 | 2 |
| 5 | モーターNo | motor number | 23 | 2 |
| 6 | ボートNo | boat number | 25 | 3 |
| 7 | 展示タイム | exhibition time | 28 | 3 |
| 8 | 進入コース | entry course | 31 | 1 |
| 9 | ST | start timing | 32 | 3 |
| 10 | レースタイム | race time | 35 | 4 |

**Disagreement to flag explicitly**: Source A's offsets, once you look at the gaps between fields
(e.g. 着順 ends at 4, but 艇番 doesn't start until 6 — a 2-char gap; 登録番号 ends at 12 but 選手名
starts at 13 — only a 1-char gap), look like they are *not* simply "prefix stripped from a denser
record" the way PC-KYOTEI's K3 is. The two are likely describing genuinely different physical layouts,
not the same layout documented two ways — i.e. this is a real disagreement, not an artifact of my
offset-shifting math. The order of fields matches between both sources; only widths/positions differ.
**Do not trust either offset table blindly — re-derive from a real downloaded K-file.**

A third source (denden56-cloud/boatrace-papertrade and tatsutatsu1028/-boatrace-ai) avoids fixed
offsets entirely and uses regex against whitespace-delimited tokens instead, e.g.
(tatsutatsu1028, paraphrased from fetched code):
```python
K_BOAT = re.compile(r"^\s*(\S{1,2})\s+([1-6])\s+(\d{4})\s(.{8})\s*(.*)$")
```
i.e. finish-code (1-2 chars) — frame (1 digit) — racer id (4 digits) — name (fixed 8-char slot) — rest
(motor/boat/exhibition/course/ST/race time, extracted from the tail via secondary token matching
rather than fixed columns). This is corroborating evidence that **developers in practice find the
per-boat line NOT perfectly fixed-width-reliable** (inconsistent run-length of spaces, numbers that
butt up against each other when they get large — e.g. one source notes "39.74117 32.11" where two
numeric fields ran together with no separating space) and resort to regex/whitespace splitting rather
than pure byte slicing, except for the name field, which is handled with its own fixed-width slot
specifically *because* racer names routinely contain embedded full-width spaces between characters
(e.g. `藤　原　　菜　希`) and would otherwise split wrong on whitespace.

### 1.3 着順 (finish position) — exceptional value codes

Two different coding schemes turned up, likely corresponding to two different record "eras" or
contexts (the PC-KYOTEI document itself presents them as two separate code tables, "着順(R3)" vs
"着順(K3)", implying the newer/batch K-file uses a different, more granular scheme than an older
R3-style per-boat record querying the live site):

**Scheme 1 — single/compound-kanji codes ("着順(R3)" table, PC-KYOTEI PDF)**:

| Code | Meaning |
|---|---|
| F | フライング返還欠場 (flying start → DQ, stake refunded) |
| L | 出遅れ返還欠場 (late start → DQ, stake refunded) |
| エ | エンスト失格 (engine stall → DQ) |
| 欠 | 欠場 (absent) |
| 失 | 前記以外の失格 (other disqualification) |
| 沈 | 沈没失格 (sank → DQ) |
| 転 | 転覆失格 (capsized → DQ) |
| 不 | 不完走失格 (did not finish → DQ) |
| 妨 | 妨害失格 (obstruction → DQ) |
| 落 | 落水失格 (fell overboard → DQ) |

This matches exactly the exception categories the user already expected (F/L/欠/転/妨/失格), plus a
few more granular ones (エ/沈/不/落) this research turned up that weren't in the user's original list.

**Scheme 2 — 2-char alphanumeric codes ("着順(K3)" table, PC-KYOTEI PDF, i.e. specifically for the
結果(艇番) K3 record that is sourced from the *download* K-file, which is the one that matters here)**:

| Code | Meaning |
|---|---|
| `F_` | フライング (flying start) |
| `K_` | 欠場 (absent, general) |
| `K0` | 欠場 — 選手責任外 (absent, not racer's fault) |
| `K1` | 欠場 — 選手責任 (absent, racer's fault) |
| `L_` | 出遅れ (late start, general) |
| `L0` | 出遅れ — 選手責任外 |
| `L1` | 出遅れ — 選手責任 |
| `S_` | 失格 (disqualified, general) |
| `S0` | 失格 — 選手責任外 |
| `S1` | 失格 — 選手責任 |
| `S2` | 他艇を妨害・失格 (obstructed another boat → DQ) |

**Confidence**: this table is from the PC-KYOTEI PDF (§3) which, per its own documentation, sources
the K1/K2/K3 records specifically from `boatrace.jp/owpc/pc/extra/data/download.html` — i.e. the same
download page the user is using. This is the single best lead found for the exact exception-code
alphabet in the *actual* K-file, but it has **not been independently cross-confirmed against a second
source quoting the literal codes** (other sources only described the concept of exception codes in
prose, e.g. "F for flying, L for late start, etc." without the compound `K0/K1/S0/S1/S2` detail).
Treat Scheme 2 as the more likely candidate for what you'll actually see in the raw K-file's 着順
field, but verify against real samples — in particular confirm whether the trailing character is
literally `_` (underscore) or a half-width/full-width space used as a placeholder.

### 1.4 Weather / wind / wave fields

Convergent across three independent sources (PC-KYOTEI code tables + teruqii's raw sample line +
denden56/tatsutatsu regexes):

- **天候 (weather)**: stored as a **literal Shift-JIS kanji word**, not a numeric code, in the actual
  K-file text — e.g. `晴`(clear)/`曇`(cloudy)/`雨`(rain)/`雪`(snow)/`霧`(fog). (PC-KYOTEI's own
  "天気コード" numeric table (1=晴, 2=曇り, 3=雨, 4=雪, 5=台風, 6=霧) exists for its *normalized DB*
  but the raw text clearly carries the kanji word itself, per the regex `r"(晴|曇|雨|雪|霧)"` found in
  tatsutatsu1028's real parser and the literal `晴　` shown in teruqii's raw sample line.)
- **風向 (wind direction)**: also literal kanji compass text (北/北北東/北東/.../北北西, 16-point
  compass), not a numeric code, per the same two corroborating sources. PC-KYOTEI's 16-entry "方角
  コード" table (00=無風, 01=北 ... 16=北北西) is presumably the *normalized* numeric encoding of this
  same text.
- **風速 (wind speed)**: literal number + `m` suffix (e.g. `1m`), unit = meters/second. Confirmed by
  both the raw sample (`風  北　　 1m`) and the regex `r"風\s+(\S+)\s+(\d+)m"`.
  **PC-KYOTEI's own code table claims a width of 2 digits, 00–99, matching this.**
- **波高 (wave height)**: **here the sources disagree on the unit.** The PC-KYOTEI normalized-DB spec
  states 波高 is 2 digits, unit = meters ("単位:ｍ 00ｍ～99ｍ"). But two independent real-parser sources
  (denden56-cloud and tatsutatsu1028) both regex-match wave height with an explicit `cm` suffix
  (`r"波\s+(\d+)cm"` / `r"波\s*(\d+)cm"`), and the raw sample line shown by teruqii literally reads
  `波　  1cm`. **Conclusion: the raw K-file almost certainly expresses wave height in centimeters
  (e.g. "1cm", "3cm"), and the PC-KYOTEI PDF's "単位:m" label for its own 波高 field is most likely a
  documentation mistake or refers to a differently-scaled internal column** — 0–99 *meter* waves at an
  inland/bay boat racing venue would be physically absurd, while 0–99 cm is entirely realistic. Do not
  blindly trust the PC-KYOTEI unit label for this one field; trust the two live-parser regexes + the
  raw sample instead.
- All four weather-ish values appear to live on the same **race header line**, interleaved with the
  race title and distance, e.g.: `1R  一般  H1800m  晴　風 北　 1m  波　 1cm` — order is
  race#/title → distance → weather → wind-direction → wind-speed → wave-height. Exact byte columns:
  **not confirmed**; every source that touches this line uses regex/whitespace splitting, not fixed
  offsets (the PC-KYOTEI normalized "結果(レースNo)" K2 record *does* give fixed widths — 天気 6 bytes,
  風向 6 bytes, 風速 2 bytes, 波高 2 bytes — see §3 — but as with the per-boat record, that's a
  reformatted record with an extra prefix, so treat the *widths* as a plausible hint and the absolute
  *offsets* as unconfirmed for the raw file).

### 1.5 決まり手 (winning technique)

Stored as literal text, one of: 逃げ / 差し / まくり / まくり差し / 抜き / 恵まれ. PC-KYOTEI's K2
record gives it a fixed 10-byte full-width-space-padded slot; not independently confirmed against a
raw sample in this research pass, but the value domain (6 literal strings) is well established from
general boat-racing reference sources and is consistent with what a reverse-engineered parser would
need to match.

### 1.6 払戻金 (payout) table — structure

From the PC-KYOTEI K2 record (field order and repeat/dead-heat-handling logic; exact byte offsets
carry the same "reformatted record, prefix stripped" caveat as above, so given here as structure, not
absolute offsets):

| Bet type (JP) | EN | Entry shape | Repeats (dead-heat allowance) | "no contest" code | "special payout" code |
|---|---|---|---|---|---|
| 単勝 | Win | 艇番(1) + 金額(7) | up to 2 | `"0"` | `"*"` |
| 複勝 | Place | 艇番(1) + 金額(7) | up to 3 | `"0"` | `"*"` |
| ２連複 | Quinella | 組番(2) + 金額(7) + 人気順(2) | up to 2 | `"00"` | `"**"` |
| 拡連複 | Wide | 組番(2) + 金額(7) + 人気順(2) | up to 5 | `"00"` | `"**"` |
| ２連単 | Exacta | 組番(2) + 金額(7) + 人気順(2) | up to 2 | `"00"` | `"**"` |
| ３連複 | Trio | 組番(3) + 金額(7) + 人気順(2) | up to 2 | `"000"` | `"***"` |
| ３連単 | Trifecta | 組番(3) + 金額(7) + 人気順(3) | up to 2 | `"000"` | `"***"` |

Live-parser confirmation (denden56/tatsutatsu, regex over the literal `単勝/複勝/２連単/.../３連複`
text labels followed by combo/amount/人気 tokens) and the teruqii raw sample agree on: (a) bet-type
order, (b) that 拡連複 legitimately repeats (3 winning combos per race, since it pays the 3
combinations among the top 3 finishers), (c) that 人気 (popularity rank) is present for every
multi-boat bet type but absent for 単勝/複勝. The 不成立/特払い marker *characters* (`0`/`00`/`000` and
`*`/`**`/`***`) come only from the PC-KYOTEI table and are **unconfirmed against a live raw sample** —
worth specifically testing against a historical race that actually had a dead-heat, void, or
carried-over payout.

---

## 2. B-file (番組表データ, pre-race entry list)

### 2.1 Record structure

Same venue/race nesting as the K-file: `STARTB` → per-venue `{venue#}BBGN ... {venue#}BEND` blocks →
inside each venue, a venue header (venue name, event title, day number) → per-race header line
(race number, race name/class, distance, entry-fixed flag, betting deadline time) → 6 per-boat entry
lines. Raw samples (medium-confidence, via tool-paraphrased fetch, not a verbatim byte dump):

```
ボートレース唐　津 　８月　１日 ヴィーナスシリーズ第 第　４日
１Ｒ 一　　般　　 Ｈ１８００ｍ 電話投票締切予定０８：５５
```

Column-header line as literally printed in the file (useful as a sanity check when visually
inspecting a real file — confirms field order):
```
艇 選手 選手 年 支 体級 全国 当地 モーター ボート 今節成績 早
番 登番 名 齢 部 重別 勝率 2率 勝率 2率 NO 2率 NO 2率 １２３４５６見
```

### 2.2 Per-boat entry line — field order and widths

This is the best-corroborated part of this whole document: **three independent sources converge
closely**, including one with an actual raw sample line character-aligned against explicit column
indices (teruqii's MATLAB code, which is 1-indexed and operates on *characters*, i.e. one full-width
kanji = one index — same semantics as Python's string indices after Shift-JIS decoding, so these two
sources are directly comparable once you convert 1-based↔0-based).

Raw sample line (teruqii, Qiita, high confidence — shown with explicit matching indices in the
source article):
```
1 4627藤原菜希33東京46A1 6.47 47.50 5.28 32.00 63 36.60 76 41.46 2S221 12
```

| Order | Field (JP) | Field (EN) | teruqii (MATLAB, 1-based char) | cstenmt (Python, 0-based char) | tatsutatsu (regex width) |
|---|---|---|---|---|---|
| 1 | 艇番 | frame number | `txt(1)` → 1 char | `c[0]` → 1 char | `[1-6]` → 1 char |
| 2 | 登録番号 | racer registration number | `txt(3:6)` → 4 chars | `c[2:6]` → 4 chars | `\d{4}` → 4 chars |
| 3 | 選手名 | racer name | implied 7–10 → 4 chars | `c[6:10]` → 4 chars | `.{4}` → 4 chars |
| 4 | 年齢 | age | `txt(11:12)` → 2 chars | `c[10:12]` → 2 chars | `\d{2}` → 2 chars |
| 5 | 支部 | branch (home prefecture, abbreviated) | implied 13–14 → 2 chars | `c[12:14]` → 2 chars | `.{2}` → 2 chars |
| 6 | 体重 | weight | `txt(15:16)` → 2 chars | `c[14:16]` → 2 chars | `\d{2}` → 2 chars |
| 7 | 級別 | class (A1/A2/B1/B2) | `txt(17:18)` → 2 chars | `c[16:18]` → 2 chars | `[AB][12]` → 2 chars |
| 8 | 全国勝率 | national win rate | `txt(19:23)` → 5 chars | `c[19:23]` → 4 chars (**disagrees**) | 5 chars |
| 9 | 全国2連率 | national 2-boat (quinella) rate | `txt(24:29)` → 6 chars | `c[24:29]` → 5 chars (**disagrees**) | 6 chars |
| 10 | 当地勝率 | local (venue) win rate | `txt(30:34)` → 5 chars | `c[30:34]` → 4 chars (**disagrees**) | 5 chars |
| 11 | 当地2連率 | local 2-boat rate | `txt(35:40)` → 6 chars | `c[36:40]` → 4 chars (**disagrees, also a gap at 34–36**) | 6 chars |
| 12 | モーター番号 | motor number | `txt(41:43)` → 3 chars | `c[41:43]` → 2 chars (**disagrees**) | 3 chars |
| 13 | モーター2連率 | motor 2-boat rate | `txt(44:49)` → 6 chars | `c[44:49]` → 5 chars (**disagrees**) | 6 chars |
| 14 | ボート番号 | boat number | `txt(50:52)` → 3 chars | `c[50:52]` → 2 chars (**disagrees**) | 3 chars |
| 15 | ボート2連率 | boat 2-boat rate | `txt(53:58)` → 6 chars | `c[53:58]` → 5 chars (**disagrees**) | 6 chars |
| 16 | 今節成績 | this-meet results (per-race-day marks, 6 digits + symbol) | — | `c[59:71]` (6×2-char pairs) | 12 chars |
| 17 | 早見（レースNo） | quick-reference race number | — | `c[71:73]` | 2 chars |

**Order is unanimous across all three sources — treat field order as solid.** Widths disagree in a
consistent, small way: teruqii (who has the one actual aligned raw-text sample, and whose indices are
internally self-consistent against that sample: `4627`=4 chars at 3–6 ✓, `33`=2 chars at 11–12 ✓,
`東京`=2 chars at 13–14 ✓, `46`=2 chars at 15–16 ✓, `A1`=2 chars at 17–18 ✓) and tatsutatsu's
independently-derived regex widths agree with each other almost exactly (both say 5/6/5/6/3/6/3/6 for
win-rate/2-rentai-rate/motor/boat fields), while cstenmt's slice widths run consistently about 1
character narrower for several of the later numeric fields. **Recommendation: trust the
teruqii/tatsutatsu widths (5,6,5,6,3,6,3,6) over cstenmt's for fields 8–15** — they're corroborated by
two independent sources including one with a verified raw-sample alignment, whereas cstenmt stands
alone on the narrower widths. Still, re-verify against your own downloaded file: cstenmt's script is
reported (by its own README) to actually work end-to-end against real downloaded data, so its narrower
widths might reflect a genuinely different file-format era/version rather than simply being wrong.

**名前 (racer name) field width — important quirk**: all three sources agree the name field is only
**4 characters** wide. This is narrow enough to truncate real Japanese names longer than 2 kanji given
+ 2 kanji surname (roughly), and the raw sample shows the file both (a) omitting the space between
characters when the name exactly fills 4 characters (`藤原菜希`, no gaps) and (b) inserting full-width
spaces between characters when the name is shorter, as seen in the *K-file's* per-boat line sample
(`藤　原　　菜　希`) — note this K-file sample is for the *same* 4-character name field concept but
in the K-file's own (differently-offset, per §1.2) per-boat record. This spacing behavior is a classic
fixed-width-Japanese-text quirk: don't naively `strip()` or split on whitespace when reading the name
column, and budget for only ~4 displayable characters (name may be abbreviated/clipped for racers with
unusually long names — not confirmed by a source, but a logical consequence of a hard 4-char field
that several blog posts allude to in passing as "名前が時々おかしい/欠ける").

### 2.3 Fields the user asked about that were NOT confirmed in this file (likely elsewhere or absent)

- **級別 (class)** — confirmed present (`A1`/`A2`/`B1`/`B2` 2-char code), per all three sources.
- **支部 (branch)** — confirmed present (2-char abbreviated prefecture/branch name in the compact
  B-file; a *separate*, wider 4–6-byte 支部/出身地 pair appears in the PC-KYOTEI normalized "出走表
  (艇番)" L3 record, but that record is sourced from the live website per §0, not from the B-file
  itself — the B-file's own 支部 field is the narrow 2-char one above).
- **今節成績 (current-meet results, 1–6)**: present as a 12-character block (per cstenmt: `c[59:71]`)
  immediately before the 早見 race-number field. Internal sub-structure (presumably 6 × 2-character
  slots, one per day of the current event, encoding finish position or a dash for "not yet run") is
  **not confirmed** by any source fetched in this pass — the column-header text block in §2.1 shows it
  labeled "今節成績１２３４５６" (i.e. columns for day 1 through day 6 of the event), which strongly
  suggests 6 slots, but exact per-slot width/encoding needs verification against a real file.

---

## 3. The "PC-KYOTEI Database" spec (tanpony5.sakura.ne.jp PDF) — what it is and how to use it

During this research a detailed PDF turned up: **"PC-KYOTEI Database フォーマット"**
(`https://tanpony5.sakura.ne.jp/sql/PC-KYOTEI%E3%83%87%E3%83%BC%E3%82%BF%E4%BB%95%E6%A7%98%E6%9B%B8.pdf`).
It is the most complete, well-organized field-level spec found in this research — but it needs a big
caveat before you use it as ground truth for the raw mbrace.or.jp files:

**What it actually documents**: a normalized relational database built by a piece of third-party
software ("PC-KYOTEI") that ingests data from *two different sources* — (a) the live
`boatrace.jp/owpc/pc/race/index` pages (record types `L1/L2/L3` "出走表", `O1`–`O6` "オッズ",
`C2/C3/C4` "直前情報", `R2/R3` "結果"), and (b) the `boatrace.jp/owpc/pc/extra/data/download.html`
bulk-download page (record types `B1/B2/B3` "番組表" and `K1/K2/K3` "結果" — **these two are the ones
relevant to this project**, plus `KI` "レーサー期別成績" which is the already-documented fan file).
Each record in this spec is prefixed with a 2-byte record-type ID (`"B1"`, `"K3"`, etc.), a 1-byte
data-classification byte, and then a 10-byte date+venue+race key (開催年4 + 開催月日4 + 競艇場コード2),
sometimes plus a 2-byte レースNo and/or 1-byte 艇番 — i.e. **every record has been given a
relational-database primary key that the raw text file almost certainly does not carry per-line.**
This explains the offset disagreements noted in §1.2/§2.2: this spec's absolute byte positions are for
*its own* reformatted records, not the original file. Field **order** and field **widths**, however,
are plausibly preserved from the source material (there's no obvious reason a reformatting tool would
reorder or resize fields, only prepend a key), which is why this document is used above as corroborating
evidence for order/width/domain, with the fixed prefix subtracted for comparison, but never cited alone
for an absolute offset into the raw mbrace file.

**What's uniquely valuable in it** (used throughout §1–§2 above, and summarized here for reference):
- Full 24-venue code table (01=桐生 … 24=大村), matching the standard well-known venue order.
- Grade code table (1=SG, 2=PG1, 3=G1, 4=G2, 5=G3, 9=一般) — believed to apply to the live-site L1
  record, not the download B-file/K-file (see §0's grade discussion).
- 16-point wind-direction code table, 6-value weather code table, 2-value sex code table.
- Two separate 着順 exception-code tables (R3-style single/compound-kanji codes, and K3-style
  2-character alphanumeric codes) — see §1.3.
- Full payout-record field shapes for all 7 bet types, including dead-heat repeat counts and the
  不成立/特払い marker characters — see §1.6.
- Decimal-scaling conventions used throughout the data (very useful even if offsets are off): ST like
  `016` = 0.16 seconds; win rates like `0580` = 5.80; 2/3-rentai rates like `03881` = 38.81%; race time
  like `1495` = "1分49秒5" (1 minute 49.5 seconds); exhibition time like `0671` = 6.71 seconds; weight
  like `524` = 52.4 kg; motor/boat numbers are right-justified when they have fewer digits than the
  field width (e.g. a 1-digit motor number in a 2-digit field, or a 2-digit boat number in a 3-digit
  field).

If you can find this same author's underlying raw-format documentation (if one exists) it would be the
ideal next source to check — this research did not find one, only the normalized-DB spec.

---

## 4. Known quirks and gotchas (collected across all sources)

- **Fixed-width "in theory", whitespace/regex-parsed "in practice"**: multiple independent, working
  parsers (denden56-cloud, tatsutatsu1028, teruqii's MATLAB series) choose to parse the K-file's
  per-boat and race-header lines via regex/whitespace-tokenization rather than pure fixed-column
  slicing, specifically because (a) numeric fields can butt up against each other when a value is
  wider than expected (one source cites `"39.74117 32.11"` — two numbers running together with no
  separating space), and (b) leading/trailing space-padding width is not perfectly consistent across
  all rows/eras of the file. The B-file's racer-stat columns seem more reliably fixed-width (three
  sources' widths agree closely there) than the K-file's results columns.
- **Full-width spaces embedded inside values**: racer names, venue names, and event titles are padded
  with/interspersed with full-width spaces (`　`, U+3000) rather than half-width spaces, and the name
  field specifically may have a full-width space inserted *between* individual kanji characters when
  the name is shorter than the fixed field width (not after it like ordinary padding) — e.g.
  `藤　原　　菜　希`. This breaks naive `.split()`/`.strip()` logic; the field must be extracted by
  character position (or the full-width spaces specifically stripped) before being treated as text.
- **Multi-byte vs single-byte counting**: once decoded from Shift-JIS to a Python `str` / MATLAB
  `char` array, every character — half-width digit/ASCII or full-width kanji/kana — occupies exactly
  one index. The *byte* length of a line in the original Shift-JIS encoding is **not** the same as its
  character length (each full-width character is 2 *bytes* but 1 *character*/index). All offsets in
  this document are character/index positions (post-decode), consistent with how every source's code
  actually indexes the text — be careful not to conflate these with raw byte offsets if you ever
  process the file before decoding, or if you use a language/library that iterates UTF-16 code units
  or raw bytes instead of logical characters.
- **Old/gaiji kanji in names**: expect characters that don't map cleanly through a standard cp932
  codec table; at least one source reports needing manual cleanup/replacement for these.
  Recommend defensive decoding (e.g. Python's `errors='replace'`, or a cp932 variant table) and
  logging any row that fails to decode cleanly rather than crashing the pipeline.
  reported.
- **Missing/placeholder values**: for races or entries that haven't happened yet or whose data is
  genuinely missing, one source reports inconsistent placeholder forms within the same column across
  different files/eras — things like `_.__`, `____`, or `K.__` instead of a real time value. Build
  your parser to tolerate several different "blank" spellings for numeric fields rather than assuming
  one canonical blank format.
  中止 (meet cancelled) handling: at least one actively-maintained parser (rhapsody0919/boatrace-ai-
  predictor, per its PR history) specifically had to add logic to distinguish "NR 中　止" (race/meet
  cancelled) from a normal result line, and separately to distinguish a full-day cancellation from a
  mid-day stoppage — i.e. the K-file apparently has a distinct literal cancellation marker/line that
  substitutes for the normal race-header-and-6-results sequence when a race or whole day is called off.
  This research could not obtain the exact marker text/format from that private repository (its PRs
  were visible via search snippets but the actual diff/code content was not fetchable), so treat
  "races can be cancelled and appear as a different line shape" as a confirmed *fact* but the *exact
  text/format* of that line as **unconfirmed — needs verification against a real file containing a
  rained-out/cancelled day**.
- **Payout repeat counts handle dead heats, not ties in general**: the "up to N repeats" structure in
  §1.6 exists specifically to allow multiple winning tickets when two or more boats cross the line
  together (同着) — don't assume the K-file always has exactly one winner line per bet type.

---

## 5. Sources actually used

Search tooling and WebFetch tool-assisted summaries were used throughout (noted inline above where a
source came through as a paraphrase rather than a verbatim quote). URLs actually fetched/consulted:

- https://tanpony5.sakura.ne.jp/sql/PC-KYOTEI%E3%83%87%E3%83%BC%E3%82%BF%E4%BB%95%E6%A7%98%E6%9B%B8.pdf
  — "PC-KYOTEI Database フォーマット" PDF spec (primary source for §3, and for code tables/payout
  structure/decimal conventions used throughout §1–2).
- https://github.com/cstenmt/boatrace — repo overview (file list).
- https://raw.githubusercontent.com/cstenmt/boatrace/master/txtTocsv_results.py — K-file parser code
  (Source A in §1.2).
- https://raw.githubusercontent.com/cstenmt/boatrace/master/txtTocsv_timetable.py — B-file parser code
  (used in §2.2 comparison table).
- https://qiita.com/teruqii/items/14bdffe71ef9ff061e55 — "MATLABで競艇の解析を始めよう（競走結果データ
  の読み込み）" — K-file raw sample lines, markers (STARTK/KBGN/KEND), race-header sample.
- https://qiita.com/teruqii/items/9aede1165e7428d3f89c — "MATLABで競艇の解析を始めよう（大量の出走表
  ファイルからデータを読み込み）" — B-file raw sample line + exact MATLAB column indices (primary
  source for §2.2's best-corroborated table).
- https://qiita.com/teruqii/items/986d4fba96544960f367 — "MATLABで競艇の解析を始めよう（払戻金の取得）"
  — payout section raw sample and structure (§1.1 item 5, §1.6).
- https://qiita.com/teruqii/items/cd6e390cff80d6686c69 — "MATLABで競艇の解析を始めよう（選手データを
  見てみよう）" — fetched but determined to describe the *fan file* (already officially documented),
  not the B-file; not used as a B-file source.
- https://qiita.com/NGOhiroshi/items/2373b8aaffd028c7e583 — K-file raw text structure / venue markers
  corroboration.
- https://qiita.com/Carl_Jonson/items/68b744da4219197e29a5 — K-file section-marker corroboration
  (`［成績］`, `---` separators), general parsing-approach description.
- https://qiita.com/Norimax/items/c500d1bf78e823e07f2b — confirms Shift-JIS/cp932 encoding, "mysterious
  format" characterization, regex-over-fixed-offset parsing approach.
- https://koji30learn.com/boatrace-getdata-text/ — confirms `shift-jis` decoding of the official text
  download; otherwise uses regex rather than documenting fixed columns.
- Web-search-only corroboration (snippets read, underlying pages not fully fetched due to being GitHub
  PR diffs not directly retrievable, or because the summarized snippet was sufficient):
  - https://github.com/rhapsody0919/boatrace-ai-predictor (and its PRs #671, #736, #781, #807, #1088,
    #1089, #1090, #1097, #1203, #1437, etc.) — corroborates: LZH/LH5 decompression + Shift-JIS decode
    approach; existence of a distinct day/meet-cancellation line format in the K-file (exact text
    unconfirmed); that K/B files are available from 2005-01-01 and contain the "full" field set
    (ST, exhibition time, lane assignment, weather, 決まり手, payouts) from 2019-04 onward (implying
    earlier files may have a reduced field set — **not independently verified, flagging for your
    awareness since your app may need to handle older files differently**).
  - https://github.com/denden56-cloud/boatrace-papertrade (`boatrace/parse.py`) — regex patterns for
    K-file weather/wind/wave and B-file fixed-width field widths (§1.4, §2.2 comparison column).
  - https://github.com/tatsutatsu1028/-boatrace-ai (`official_download.py`) — regex patterns for
    K-file race header/per-boat/payout, and B-file `B_BOAT_HEAD` regex + field widths (§1.2, §1.4,
    §1.6, §2.2 comparison column).
  - https://boat-advisor.com/soft/manual/db_file.htm — reviewed, found to describe a different legacy
    "Boat Advisor" `.bad` file naming scheme, not useful for byte-level layout.
  - A Yahoo!知恵袋 thread and surrounding search snippets — source for the `STARTK`/`{venue}KBGN`/
    `{venue}BBGN` file-marker claim in §0 (medium confidence, not independently verified against a
    fetched raw file).

Sources checked and found **not** to contain usable layout detail (listed so you don't re-waste time
on them): https://note.com/magic_hare3269/n/n3e715f3e5f00, https://teimon.jp/okawari_colab_1/,
https://teimon.jp/zutto_colab_3/, https://qiita.com/taxinumber1729/items/643f708eb19524e3d1e7,
https://qiita.com/yyyyyy666/items/1a28cc2f84ea24d6ab4a, https://zenn.dev/nishizumi_nobu/scraps/22ab6dc00bbf11
(confirms cp932 + "mysterious format" characterization but no concrete offsets),
https://note.com/bottore/n/ne88f2e8fb146 (covers website-scraping CSVs, not the mbrace lzh files).
