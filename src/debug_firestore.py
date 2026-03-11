import os
import sys
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

def debug_firestore():
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    try:
        cred = service_account.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(
            project=cred.project_id, 
            credentials=cred, 
            database='livinginsider-scraping'
        )
        collection_name = 'Leads'
        
        print(f"[DEBUG] Checking collection: {collection_name}")
        # ดึงมา 10 รายการเพื่อดูโครงสร้าง
        docs = db.collection(collection_name).limit(10).get()
        
        if not docs:
            print("[DEBUG] No documents found in collection 'Leads'.")
            return

        print(f"[DEBUG] Total found: {len(docs)} documents.")
        for doc in docs:
            data = doc.to_dict()
            print(f"- ID: {doc.id} | api_synced: {data.get('api_synced', 'NOT_FOUND')}")
            
    except Exception as e:
        print(f"[DEBUG] Error: {e}")

if __name__ == "__main__":
    debug_firestore()
