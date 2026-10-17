import re
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (personal research script; contact: k.kishimoto@sustella-jp.com)"}
url = "https://www.boatrace.jp/owpc/pc/race/monthlyschedule?year=2026&month=5"
r = requests.get(url, headers=HEADERS, timeout=30)
r.encoding = "cp932"
text = r.text

pattern = re.compile(
    r'<td([^>]*)>\s*(?:<a href="/owpc/pc/race/assen\?jcd=(\d+)&(?:amp;)?hd=(\d+)"[^>]*>(.*?)</a>)?\s*</td>',
    re.S
)
matches = pattern.findall(text)
with open(r"C:\Users\kouki\OneDrive\ドキュメント\boatrace-app\docs\schedule_scrape_test.txt", "w", encoding="utf-8") as f:
    f.write(f"total td-with-colspan matches: {len(matches)}\n")
    for attrs, jcd, hd, title in matches:
        cls = re.search(r'class\s*=\s*"([^"]*)"', attrs)
        colspan = re.search(r'colspan\s*=\s*"(\d+)"', attrs)
        f.write(f"jcd={jcd!r} hd={hd!r} colspan={colspan.group(1) if colspan else None} class={cls.group(1) if cls else None} title={title.strip() if title else ''}\n")
