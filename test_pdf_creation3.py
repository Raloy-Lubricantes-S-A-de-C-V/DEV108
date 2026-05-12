import fitz
import re

def estampar_variables_en_pdf(pdf_path, variables_dict):
    doc = fitz.open(pdf_path)
    modificado = False
    
    for page in doc:
        text = page.get_text("text")
        for key, value in variables_dict.items():
            pattern = r"\{\{" + re.escape(key) + r"(?::.*?)?\}\}"
            matches = re.findall(pattern, text, re.DOTALL)
            
            etiquetas_a_buscar = list(set(matches))
            if not etiquetas_a_buscar:
                etiquetas_a_buscar = [f"{{{{{key}}}}}"]
            
            for etiqueta in etiquetas_a_buscar:
                instancias = page.search_for(etiqueta)
                if instancias:
                    instancias.sort(key=lambda r: (r.y0, r.x0))
                    for rect in instancias:
                        rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                        page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                    page.apply_redactions()
                    first_rect = instancias[0]
                    y_alineado = first_rect.y1 - 2.5
                    page.insert_text((first_rect.x0, y_alineado), str(value).upper(), fontsize=11, fontname="hebo", color=(0, 0, 0))
                    modificado = True

    if modificado: doc.save("test_tags_mod2.pdf")
    doc.close()

estampar_variables_en_pdf("test_tags.pdf", {"LEVEL_POSTION": "DIRECTIVO", "NORMAL": "TEST VAL"})

doc = fitz.open("test_tags_mod2.pdf")
words = doc[0].get_text("words")
for w in words: print(w[4])
