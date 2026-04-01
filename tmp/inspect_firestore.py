import os
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

# From src/services/firestore_service.py
# credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
# For this inspection, we'll try the known JSON file if env doesn't have it
credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE') or 'agentic-scraping-pptd-f7bc092f86f3.json'
database_id = 'livinginsider-scraping'

try:
    if os.path.exists(credentials_file):
        cred = service_account.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(project=cred.project_id, credentials=cred, database=database_id)
    else:
        db = firestore.Client(database=database_id)
        
    collection_name = 'Leads'
    
    print(f"--- Fetching 1 document from {collection_name} ---")
    docs = db.collection(collection_name).limit(1).stream()
    
    found = False
    for doc in docs:
        found = True
        data = doc.to_dict()
        print(f"ID: {doc.id}")
        
        # Check for analysis subcollection
        analysis_doc = doc.reference.collection('Analysis_Results').document('evaluation').get()
        if analysis_doc.exists:
            data['ai_analysis'] = analysis_doc.to_dict()
            
        import json
        print(json.dumps(data, indent=2, ensure_ascii=False))
    
    if not found:
        print("No documents found in collection.")
        
except Exception as e:
    print(f"Error: {e}")
