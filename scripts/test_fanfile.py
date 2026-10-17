import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_fanfile import parse_fan_file, RECORD_LENGTH

p = ROOT / "data" / "raw" / "kibetsu" / "fan2604.txt"
raw = p.read_bytes()
print("RECORD_LENGTH", RECORD_LENGTH)
records, errors = parse_fan_file(raw)
print("records:", len(records), "errors:", len(errors))
for e in errors[:10]:
    print("ERR", e)
r = records[0]
print(r)
