import fitz
import re

doc = fitz.open("media/PRUEBA INTEGRACIÓN-EQUIPO-API-RALOY-2026-000_temp.pdf") # test the first page
page = doc[0]

text = page.get_text("text")
matches = re.findall(r"\{\{LEVEL_POSTION:.*?\}\}", text, re.DOTALL)
print("Matches LEVEL_POSTION:", matches)

matches_all = re.findall(r"\{\{.*?\}\}", text, re.DOTALL)
print("All tags found:", len(matches_all), matches_all[:5])

for m in matches_all:
    rects = page.search_for(m)
    if rects:
        print(f"Found rects for {m[:20]}...: {len(rects)} rects")
    else:
        print(f"NOT FOUND: {m[:20]}...")
