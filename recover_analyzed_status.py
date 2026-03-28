import os
from src.services.firestore_service import FirestoreService

def recover_analyzed_status():
    fs = FirestoreService()
    print("Reading 'Launch_Properties'... Fetching stats now.")
    
    docs = fs.db.collection("Launch_Properties").get()
    
    if not docs:
        print("Collection is empty.")
        return
        
    batch = fs.db.batch()
    recovered_count = 0
    total_scanned = 0
    
    for doc in docs:
        data = doc.to_dict()
        total_scanned += 1
        
        # Check if room_color exists but analyzed is not True
        if data.get("room_color") and (data.get("analyzed") is False or data.get("analyzed") is None):
            batch.update(doc.reference, {"analyzed": True})
            recovered_count += 1
            
            if recovered_count % 500 == 0:
                batch.commit()
                batch = fs.db.batch()
                print(f"   Processed {recovered_count} properties...")

    if recovered_count > 0:
        batch.commit()
        
    print(f"DONE! Recovered {recovered_count} properties out of {total_scanned} total scanned.")

if __name__ == "__main__":
    recover_analyzed_status()
