import os
from src.services.firestore_service import FirestoreService

def reset_empty_scraped():
    fs = FirestoreService()
    if not fs.db:
        print("❌ Cannot connect to Firestore.")
        return

    COLLECTION = "Leads"
    print(f"🔍 Searching for bad scraped data in '{COLLECTION}'...")
    
    # ดึงเฉพาะที่มีธง zmyh_scraped = True
    docs = fs.db.collection(COLLECTION).where("zmyh_scraped", "==", True).get()
    
    reset_count = 0
    total_checked = 0
    
    for doc in docs:
        total_checked += 1
        data = doc.to_dict()
        
        facs = data.get("zmyh_facilities")
        built = data.get("zmyh_built_year")
        
        # 🕵️‍♂️ จับทั้ง 2 กรณี:
        # 1. ไม่มีฟิลด์เลย (None)
        # 2. มีฟิลด์แต่เป็น empty string "" หรือ list ว่าง []
        facs_empty = not facs or facs == "" or facs == []
        built_empty = not built or built == ""
        
        if facs_empty and built_empty:
            doc.reference.update({
                "zmyh_scraped": False,
                # ลบ field ที่เป็น empty string ทิ้งด้วย
                "zmyh_built_year": None,
                "zmyh_developer": None,
                "zmyh_total_units": None,
            })
            reset_count += 1
            print(f"  [RESET] {doc.id} - {data.get('sheet_ชื่อโครงการ') or data.get('project_name')}")
            
    print(f"\n✅ Done!")
    print(f"📊 Total checked (zmyh_scraped=True): {total_checked}")
    print(f"🔄 Total reset (empty data): {reset_count}")
    
if __name__ == "__main__":
    reset_empty_scraped()
