import duckdb
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
con = duckdb.connect(str(ROOT / "data" / "sample.duckdb"))
print(con.execute("""
    SELECT date, count(*) n,
           sum(CASE WHEN motor_2rentai_rate > 0 THEN 1 ELSE 0 END) motor2_nonzero,
           sum(CASE WHEN boat_2rentai_rate > 0 THEN 1 ELSE 0 END) boat2_nonzero,
           avg(motor_2rentai_rate) avg_motor2
    FROM program_entries GROUP BY 1 ORDER BY 1
""").df().to_string())
print()
print(con.execute("SELECT * FROM program_entries WHERE date = '261001' LIMIT 6").df().to_string())
