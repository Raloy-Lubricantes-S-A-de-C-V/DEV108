import pymongo
import json

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
col = db['motor_firmas_directoriofirmas']

print("Usuarios:")
for u in col.find():
    print(f"ID: {u.get('id')} - Email: {u.get('email')} - Permisos type: {type(u.get('permisos_portal'))} - Value: {u.get('permisos_portal')}")

