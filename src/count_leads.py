import os
import sys
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

def count_leads():
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    try:
        cred = service_account.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(
            project=cred.project_id, 
            credentials=cred, 
            database='livinginsider-scraping'
        )
        collection_name = 'Leads'
        
        print(f"[Firestore] Checking collection: {collection_name}...")
        
        # ใช้วิธีดึงทุกลูก (stream) เพื่อมานับ หรือใช้ aggregation query (ถ้ามี)
        # เพื่อความรวดเร็วและประหยัด ลองใช้ count aggregation
        count_query = db.collection(collection_name).count()
        total_count = count_query.get()[0][0].value
        
        print(f"Total documents: {total_count}")
        
        # แยกตามโซน (ถ้าเราบันทึก zone ไว้)
        synced_count = db.collection(collection_name).where("api_synced", "==", True).count().get()[0][0].value
        unsynced_count = db.collection(collection_name).where("api_synced", "==", False).count().get()[0][0].value
        
        print(f"Synced: {synced_count}")
        print(f"Unsynced: {unsynced_count}")
        
        print("\nReason why it might be lower than expected:")
        print("1. Deduplication: Using Listing ID as document name (Updates instead of creates)")
        print("2. Filtered: Current config only scrapes 'Condo'")
        print("3. Filtered: Only 'OWNER' leads are saved")
        print("4. Filtered: Price limit filter")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    count_leads()
