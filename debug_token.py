import pymongo
from bson import json_util
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']

col_proc = db['motor_firmas_procesofirma']
proc = col_proc.find_one({"token_acceso": "5b74dc4e-96fa-4dfc-8e05-63fff7f2bf72"})
if not proc:
    # Try as UUID if string fails, djongo might store it differently
    import uuid
    proc = col_proc.find_one({"token_acceso": uuid.UUID("5b74dc4e-96fa-4dfc-8e05-63fff7f2bf72")})

if proc:
    print("PROC reference_id:", proc.get("reference_id"))
    print("PROC dir_drive:", proc.get("dir_drive"))
    print("PROC document_variables:", proc.get("document_variables"))
    print("PROC summary_data:", proc.get("summary_data"))
    
    col_plan = db['motor_firmas_plantillaformulario']
    # Check if there is any plan with this dir_drive
    plans = list(col_plan.find({"drive_folder_id": proc.get("dir_drive")}))
    if not plans:
        plans = list(col_plan.find({"carpeta_firmados_id": proc.get("dir_drive")}))
        
    print(f"Found {len(plans)} plans matching dir_drive.")
    for p in plans:
        print(" - PLAN nombre:", p.get("nombre"))
        print(" - PLAN formato_folio:", p.get("formato_folio"))
        print(" - PLAN variables:", json.dumps(p.get("variables"), default=json_util.default)[:200], "...")
else:
    print("Process not found for token.")
