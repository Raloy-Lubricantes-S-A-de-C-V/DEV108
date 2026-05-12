import pymongo
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
col_proc = db['motor_firmas_procesofirma']
col_plan = db['motor_firmas_plantillaformulario']

token = "295e7ac1-5e1d-4486-9294-820e9d83bcb9"
import uuid
proc = col_proc.find_one({"token_acceso": uuid.UUID(token)})
if not proc:
    proc = col_proc.find_one({"token_acceso": token})

if proc:
    content_option = {}
    labels_map = {}
    plantilla_encontrada = None
    
    if proc.get('exec_mode') == 'form' and proc.get('dir_drive'):
        plans = list(col_plan.find({"drive_folder_id": proc.get("dir_drive")}))
        if not plans:
            plans = list(col_plan.find({"carpeta_firmados_id": proc.get("dir_drive")}))
            
        for p in plans:
            formato = p.get("formato_folio", "")
            prefix = formato.split('-0')[0] if formato else ''
            if prefix and proc.get("reference_id").startswith(prefix):
                plantilla_encontrada = p
                break
        if not plantilla_encontrada and plans:
            plantilla_encontrada = plans[0]
            
        if plantilla_encontrada and plantilla_encontrada.get("variables"):
            vars_list = plantilla_encontrada.get("variables")
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
                        
    doc_vars = proc.get("document_variables", {})
    while isinstance(doc_vars, str):
        try:
            parsed = json.loads(doc_vars)
            if parsed == doc_vars: break
            doc_vars = parsed
        except:
            break
    if not isinstance(doc_vars, dict):
        doc_vars = {}
        
    firmantes = proc.get("firmantes", [])
    while isinstance(firmantes, str):
        try:
            parsed = json.loads(firmantes)
            if parsed == firmantes: break
            firmantes = parsed
        except:
            break
    if not isinstance(firmantes, list):
        firmantes = []
        
    firmante_actual = firmantes[0] if firmantes else {}
    for f in firmantes:
        if isinstance(f, dict) and f.get("token_firmante") == "e402d0f4-55bf-4868-a3e6-d4b5d9ed78d7":
            firmante_actual = f
            break

    campos_a_llenar = []
    if proc.get('exec_mode') == 'form':
        for key, em in doc_vars.items():
            if em == firmante_actual.get('email') and key not in proc.get("valores_capturados", {}):
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

    print("Resulting campos_a_llenar length:", len(campos_a_llenar))
    for c in campos_a_llenar[:3]:
        print(c)
else:
    print("Process not found")
