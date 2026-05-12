import pymongo
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
col_proc = db['motor_firmas_procesofirma']
col_plan = db['motor_firmas_plantillaformulario']

proc = col_proc.find_one({"reference_id": "SHT6F-00005"})
plans = list(col_plan.find({"drive_folder_id": proc.get("dir_drive")}))
plantilla_encontrada = plans[0]

vars_list = plantilla_encontrada.get("variables")
while isinstance(vars_list, str):
    parsed = json.loads(vars_list)
    if parsed == vars_list: break
    vars_list = parsed

print("Vars_list has", len(vars_list), "items.")
print(vars_list[5]) # LEVEL_POSTION
print(vars_list[6]) # OFFICE

content_option = {}
for v in vars_list:
    if isinstance(v, dict):
        if v.get('type') == 'option' and 'content-option' in v:
            content_option[v['key']] = v['content-option']
            
print("Content option keys:", list(content_option.keys()))
