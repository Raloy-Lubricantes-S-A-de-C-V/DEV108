import fitz

doc = fitz.open()
page = doc.new_page()
page.insert_text((50, 50), "{{MAIL_PERSONALIZADO_GENERI\nCO}}")
doc.save("test_flex.pdf")
doc.close()

doc = fitz.open("test_flex.pdf")
page = doc[0]
print("Search for:", page.search_for("{{MAIL_PERSONALIZADO_GENERI\nCO}}"))
