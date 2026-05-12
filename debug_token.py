import pymongo
from bson import json_util
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']

col_proc = db['motor_firmas_procesofirma']
token = "295e7ac1-5e1d-4486-9294-820e9d83bcb9"
proc = col_proc.find_one({"token_acceso": token})
if not proc:
    import uuid
    proc = col_proc.find_one({"token_acceso": uuid.UUID(token)})

print("document_variables type:", type(proc.get("document_variables")))
print("document_variables val:", repr(proc.get("document_variables"))[:100])

col_plan = db['motor_firmas_plantillaformulario']
plan = col_plan.find_one({"drive_folder_id": proc.get("dir_drive")})
if plan:
    print("variables type:", type(plan.get("variables")))
    print("variables val:", repr(plan.get("variables"))[:100])
