import pymongo
from bson import json_util
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']

col_proc = db['motor_firmas_procesofirma']
proc = col_proc.find_one({"reference_id": "SHT6F-00001"})
print("PROC dir_drive:", proc.get("dir_drive"))

col_plan = db['motor_firmas_plantillaformulario']
plan = col_plan.find_one({"nombre": "SOLICITUD DE HERRAMIENTAS DE TRABAJO 6 FIRMAS"})
print("PLAN drive_folder_id:", plan.get("drive_folder_id"))
print("PLAN carpeta_firmados_id:", plan.get("carpeta_firmados_id"))
print("PLAN formato_folio:", plan.get("formato_folio"))
