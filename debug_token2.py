from motor_firmas.models import ProcesoFirma, PlantillaFormulario
import json

proceso = ProcesoFirma.objects.filter(token_acceso="295e7ac1-5e1d-4486-9294-820e9d83bcb9").first()
content_option = {}
labels_map = {}

print("EXEC MODE:", proceso.exec_mode, "DIR DRIVE:", proceso.dir_drive)

if proceso.exec_mode == 'form' and proceso.dir_drive:
    plantillas = PlantillaFormulario.objects.filter(drive_folder_id=proceso.dir_drive)
    if not plantillas.exists():
        plantillas = PlantillaFormulario.objects.filter(carpeta_firmados_id=proceso.dir_drive)
        
    print("Found templates:", plantillas.count())
    plantilla_encontrada = None
    for p in plantillas:
        prefix = p.formato_folio.split('-0')[0] if p.formato_folio else ''
        print("Template:", p.nombre, "Prefix:", prefix, "Matches:", proceso.reference_id.startswith(prefix))
        if prefix and proceso.reference_id.startswith(prefix):
            plantilla_encontrada = p
            break
    if not plantilla_encontrada and plantillas.exists():
        plantilla_encontrada = plantillas.first()
        
    if plantilla_encontrada and plantilla_encontrada.variables:
        vars_list = plantilla_encontrada.variables
        print("Variables is type:", type(vars_list))
        if isinstance(vars_list, str):
            try:
                vars_list = json.loads(vars_list)
                print("JSON parsed to:", type(vars_list))
            except Exception as e:
                print("JSON parse error:", e)
                vars_list = []
                
        for v in vars_list:
            if isinstance(v, dict):
                labels_map[v.get('key')] = v.get('label', v.get('key'))
                if v.get('type') == 'option' and 'content-option' in v:
                    content_option[v['key']] = v['content-option']
                    
print("CONTENT OPTION KEYS:", content_option.keys())
print("LABELS MAP KEYS:", labels_map.keys())

document_variables = proceso.document_variables
print("Doc variables type:", type(document_variables))
if isinstance(document_variables, str):
    try:
        document_variables = json.loads(document_variables)
    except:
        pass
print("Doc variables keys:", list(document_variables.keys())[:5])

campos_a_llenar = []
if proceso.exec_mode == 'form':
    for key, em in document_variables.items():
        if key not in proceso.valores_capturados:
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
            
print("CAMPOS CON OPCIONES:")
for c in campos_a_llenar:
    if c['options']:
        print(c['key'], c['options'])
