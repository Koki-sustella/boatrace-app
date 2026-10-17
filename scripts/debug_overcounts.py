import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_kfile import parse_k_file

p = ROOT / "data" / "raw" / "kfile" / "K261001.TXT"
text = p.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
races, boats, _ = parse_k_file(text, "261001")

from collections import Counter
c = Counter((b.venue_code, b.race_no) for b in boats)
bad = {k: v for k, v in c.items() if v != 6}
print("races with != 6 boat rows:", bad)
for (venue, rno), n in bad.items():
    rows = [b for b in boats if b.venue_code == venue and b.race_no == rno]
    for r in rows:
        print(venue, rno, r.finish, r.frame, r.reg_no, r.name, r.is_exception, r.exception_label)
