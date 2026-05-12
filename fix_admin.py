import pymongo

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
col = db['motor_firmas_administradorportal']

col.update_one({"email": "pjimenezb@raloy.com.mx"}, {"$set": {"es_superadmin": True}})
admin = col.find_one({"email": "pjimenezb@raloy.com.mx"})
print("Updated admin:", admin)
