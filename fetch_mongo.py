import pymongo
from bson import json_util
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
col = db['motor_firmas_plantillaformulario']

# Query latest templates
cursor = col.find({}).sort("created_at", -1).limit(2)
for doc in cursor:
    print("--- NOMBRE:", doc.get("nombre"))
    print("VARIABLES:", json.dumps(doc.get("variables"), default=json_util.default, indent=2))
