import fitz
import re

doc = fitz.open("test_tags.pdf")
page = doc[0]

text = page.get_text("text")
# regex to find {{LEVEL_POSTION:...}} across newlines
matches = re.findall(r"\{\{LEVEL_POSTION:.*?\}\}", text, re.DOTALL)
print("Matches found:", matches)

if matches:
    for m in matches:
        # We can search for the exact string including newlines!
        rects = page.search_for(m)
        print("Rects for exact match:", rects)
