import json
import sys

class Proceso:
    def __init__(self):
        self.exec_mode = 'form'
        self.dir_drive = '1sCj-iPiNtyitSHz5O2Mv3KSDGZiDDgf0'
        self.reference_id = 'SHT6F-00005'
        self.document_variables = json.dumps({"COMPANY": "user@raloy.com.mx", "LEVEL_POSTION": "user@raloy.com.mx"})
        self.valores_capturados = {}
        self.summary_data = {}

class Plantilla:
    def __init__(self):
        self.nombre = 'Plantilla 1'
        self.formato_folio = 'SHT6F-00000'
        self.variables = json.dumps([
            {"key": "COMPANY", "label": "Empresa", "type": "text"},
            {"key": "LEVEL_POSTION", "label": "Nivel", "type": "option", "content-option": ["ALTA", "BAJA"]}
        ])

proceso = Proceso()
plantillas = [Plantilla()]
firmante_actual = {'email': 'user@raloy.com.mx'}

content_option = {}
labels_map = {}

plantilla_encontrada = plantillas[0]

if plantilla_encontrada and plantilla_encontrada.variables:
    import json
    vars_list = plantilla_encontrada.variables
    
    # Djongo might stringify or double-stringify the list
    while isinstance(vars_list, str):
        try:
            parsed = json.loads(vars_list)
            if parsed == vars_list: break
            vars_list = parsed
        except:
            break
            
    if not isinstance(vars_list, list):
        vars_list = []
            
    for v in vars_list:
        if isinstance(v, dict):
            labels_map[v.get('key')] = v.get('label', v.get('key'))
            if v.get('type') == 'option' and 'content-option' in v:
                content_option[v['key']] = v['content-option']

print("CONTENT OPTION:", content_option)

campos_a_llenar = []
if proceso.exec_mode == 'form':
    import json
    doc_vars = proceso.document_variables
    while isinstance(doc_vars, str):
        try:
            parsed = json.loads(doc_vars)
            if parsed == doc_vars: break
            doc_vars = parsed
        except:
            break
    if not isinstance(doc_vars, dict):
        doc_vars = {}
        
    for key, em in doc_vars.items():
        if em == firmante_actual['email'] and key not in proceso.valores_capturados:
            opciones = content_option.get(key)
            if isinstance(opciones, str):
                 opciones = [o.strip() for o in opciones.split(',') if o.strip()]
            elif not isinstance(opciones, list):
                 opciones = None
            
            campos_a_llenar.append({
                'key': key,
                'label': labels_map.get(key, key),
                'options': opciones
            })

print("CAMPOS:")
for c in campos_a_llenar:
    print(c)
