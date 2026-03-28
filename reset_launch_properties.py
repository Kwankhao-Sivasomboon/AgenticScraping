import os
from src.services.firestore_service import FirestoreService

def reset_all_for_reanalysis():
    fs = FirestoreService()
    print("Resetting 'Launch_Properties'... Fetching docs.")
    
    docs = fs.db.collection("Launch_Properties").get()
    
    if not docs:
        print("No documents found in 'Launch_Properties' collection.")
        return
        
    print(f"Found {len(docs)} documents. Resetting analyzed=False and uploaded=False...")
    
    batch = fs.db.batch()
    count = 0
    
    for doc in docs:
        batch.update(doc.reference, {
            "analyzed": False,
            "uploaded": False 
        })
        count += 1
        
        if count % 500 == 0:
            batch.commit()
            batch = fs.db.batch()
            print(f"   Updated {count} records...")

    batch.commit()
    print(f"SUCCESS! All {count} records reset. Ready for Step 2.")

if __name__ == "__main__":
    reset_all_for_reanalysis()
