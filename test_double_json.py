import json

raw_from_db = '"[{\\"key\\": \\"COMPANY\\"}]"'
print("Type of raw_from_db:", type(raw_from_db))

try:
    parsed1 = json.loads(raw_from_db)
    print("Parsed1 type:", type(parsed1))
    print("Parsed1 val:", parsed1)
    
    if isinstance(parsed1, str):
        parsed2 = json.loads(parsed1)
        print("Parsed2 type:", type(parsed2))
        print("Parsed2 val:", parsed2)
except Exception as e:
    print("Error:", e)
