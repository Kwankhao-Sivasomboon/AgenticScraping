import os
import sys
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

def migrate_firestore_tags():
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    try:
        cred = service_account.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(
            project=cred.project_id, 
            credentials=cred, 
            database='livinginsider-scraping'
        )
        collection_name = 'Leads'
        
        print(f"[MIGRATION] Starting migration for: {collection_name}")
        
        docs = db.collection(collection_name).get()
        
        updated_count = 0
        skipped_count = 0
        
        batch = db.batch()
        batch_count = 0
        
        for doc in docs:
            data = doc.to_dict()
            if 'api_synced' not in data:
                batch.update(doc.reference, {"api_synced": False})
                updated_count += 1
                batch_count += 1
                
                if batch_count >= 400:
                    batch.commit()
                    batch = db.batch()
                    batch_count = 0
                    print(f"[MIGRATION] Committed batch...")
            else:
                skipped_count += 1
                
        if batch_count > 0:
            batch.commit()
            
        print(f"\n[DONE] Migration Finished!")
        print(f" - Updated: {updated_count} documents")
        print(f" - Skipped: {skipped_count} documents")
        
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    migrate_firestore_tags()
