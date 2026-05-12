import fitz

def test_estampar_variables(pdf_path, variables_dict):
    doc = fitz.open(pdf_path)
    modificado = False
    for key, value in variables_dict.items():
        etiqueta_exacta = f"{{{{{key}}}}}"
        prefijo = f"{{{{{key}:"
        
        for page in doc:
            instancias = page.search_for(etiqueta_exacta)
            
            if not instancias:
                words = page.get_text("words")
                for w in words:
                    texto = w[4]
                    if texto.startswith(prefijo) and texto.endswith("}}"):
                        instancias.append(fitz.Rect(w[0], w[1], w[2], w[3]))

            for rect in instancias:
                rect_borrar = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
                page.add_redact_annot(rect_borrar, fill=(1, 1, 1))
                page.apply_redactions()
                y_alineado = rect.y1 - 2.5
                page.insert_text((rect.x0, y_alineado), str(value).upper(), fontsize=11, fontname="hebo",
                                 color=(0, 0, 0))
                modificado = True
    if modificado: doc.save("test_tags_mod.pdf")
    doc.close()

test_estampar_variables("test_tags.pdf", {"LEVEL_POSTION": "DIRECTIVO", "NORMAL": "TEST VAL"})

doc = fitz.open("test_tags_mod.pdf")
words = doc[0].get_text("words")
for w in words: print(w[4])
