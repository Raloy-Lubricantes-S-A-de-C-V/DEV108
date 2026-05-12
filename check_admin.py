import pymongo

client = pymongo.MongoClient("mongodb://admin_mongo:auPnlS4PIT058ZmWuU82@santiagoraloy.fortiddns.com:29910/ia-peter?authSource=admin")
db = client['ia-peter']
col = db['motor_firmas_administradorportal']

admin = col.find_one({"email": "pjimenezb@raloy.com.mx"})
if admin:
    print("Admin found:", admin)
else:
    print("Admin not found in MongoDB")
