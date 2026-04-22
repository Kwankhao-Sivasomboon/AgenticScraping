import os
from src.services.firestore_service import FirestoreService

def check_status():
    fs = FirestoreService()
    if not fs.db: return
    
    COLLECTION = "Leads"
    print(f"📊 Checking status for '{COLLECTION}'...")
    
    docs = fs.db.collection(COLLECTION).get()
    
    total = 0
    has_zmyh_data = 0
    has_facilities = 0
    scraped_flag_true = 0
    
    for doc in docs:
        total += 1
        data = doc.to_dict()
        
        # เช็คว่ามีข้อมูล ZmyHome ตัวใดตัวหนึ่งหรือไม่
        zmyh_keys = [k for k in data.keys() if k.startswith("zmyh_") and k != "zmyh_scraped"]
        if zmyh_keys:
            has_zmyh_data += 1
            if data.get("zmyh_facilities"):
                has_facilities += 1
        
        if data.get("zmyh_scraped") == True:
            scraped_flag_true += 1
            
    print("-" * 35)
    print(f"📈 Total Leads in Firestore: {total}")
    print(f"✅ Leads with ANY Zmyh Data: {has_zmyh_data} ({ (has_zmyh_data/total)*100 if total > 0 else 0 :.1f}%)")
    print(f"   ∟ With Facilities: {has_facilities}")
    print(f"🚩 Scraped Flag (True): {scraped_flag_true}")
    print(f"⏳ Leads needing Work: {total - has_zmyh_data}")
    print("-" * 35)

if __name__ == "__main__":
    check_status()
