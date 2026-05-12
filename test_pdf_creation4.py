import fitz
doc = fitz.open("test_tags.pdf")
words = doc[0].get_text("words")
for w in words: print(w[4])
