import pymongo

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
proc = db['motor_firmas_procesofirma'].find_one({"reference_id": "SHT6F-00005"})

print("PROC ref:", proc.get("reference_id"))
plans = list(db['motor_firmas_plantillaformulario'].find({"drive_folder_id": proc.get("dir_drive")}))

print("Found plans:", len(plans))
for i, p in enumerate(plans):
    print(f"PLAN {i}:", p.get("nombre"), "folio:", p.get("formato_folio"))
    # let's print the variableLEVEL_POSTION
    import json
    v = p.get("variables")
    while isinstance(v, str): v = json.loads(v)
    for var in v:
        if var.get("key") == "LEVEL_POSTION":
            print("  LEVEL_POSTION var:", var)
            
