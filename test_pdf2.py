import fitz

doc = fitz.open("media/EQUIPOS-FOLIO00000.pdf") 
page = doc[0]

words = page.get_text("words")
for w in words:
    if "OFFICE" in w[4] or "LEVEL" in w[4] or "CONDITION" in w[4]:
        print("WORD:", w[4])

