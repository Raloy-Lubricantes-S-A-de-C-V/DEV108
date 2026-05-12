import fitz
doc = fitz.open("media/CONTRATO-EQUIPOS-0000.pdf") # let's see if this has tags
page = doc[0]
print("search_for {{LEVEL_POSTION:", page.search_for("{{LEVEL_POSTION:"))
print("words matching LEVEL_POSTION:")
for w in page.get_text("words"):
    if "LEVEL_POSTION" in w[4]:
        print(w)
