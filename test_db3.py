import pymongo
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
proc = db['motor_firmas_procesofirma'].find_one({"reference_id": "SHT6F-00005"})
firmantes = proc.get('firmantes')
print("firmantes type:", type(firmantes))
if isinstance(firmantes, str):
    firmantes = json.loads(firmantes)
print("firmantes:", firmantes)
