import os
from src.services.firestore_service import FirestoreService
from dotenv import load_dotenv

load_dotenv()

def reset_uploaded_status():
    fs = FirestoreService()
    # เลือก Collection ที่ต้องการ Reset
    collections = ["Launch_Properties", "arnon_properties"]
    
    for coll_name in collections:
        print(f"🔄 Resetting 'uploaded' status in collection: {coll_name}...")
        docs = fs.db.collection(coll_name).where("uploaded", "==", True).stream()
        
        count = 0
        batch = fs.db.batch()
        
        for doc in docs:
            batch.update(doc.reference, {"uploaded": False})
            count += 1
            
            # Commit ทุก 500 รายการ (ข้อจำกัดของ Firestore Batch)
            if count % 500 == 0:
                batch.commit()
                batch = fs.db.batch()
                print(f"   ✅ Reset {count} docs...")
        
        batch.commit()
        print(f"✨ Finished resetting {count} docs in {coll_name}.\n")

if __name__ == "__main__":
    reset_uploaded_status()
