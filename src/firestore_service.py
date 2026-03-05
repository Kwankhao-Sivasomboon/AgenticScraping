import os
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

class FirestoreService:
    def __init__(self):
        """Initialize connection to Google Cloud Firestore."""
        self.credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
        
        # Prevent "app already exists" error during multiple instantiations
        if not firebase_admin._apps:
            try:
                cred = credentials.Certificate(self.credentials_file)
                firebase_admin.initialize_app(cred)
            except Exception as e:
                print(f"Error initializing Firebase App: {e}")
        
        try:
            self.db = firestore.client()
            self.collection_name = 'Leads'
        except Exception as e:
            print(f"Error initializing Firestore Client: {e}")
            self.db = None

    def is_listing_exists(self, listing_id):
        """
        Deduplication Logic: Check if Listing ID exists in Firestore.
        Uses .get().exists which is highly efficient.
        """
        if not self.db:
            return False
            
        try:
            doc_ref = self.db.collection(self.collection_name).document(str(listing_id))
            doc = doc_ref.get()
            return doc.exists
        except Exception as e:
            print(f"Error checking Firestore for ID {listing_id}: {e}")
            # If error, maybe assume it doesn't exist to process it, or assume it does to be safe. 
            return False

    def save_listing(self, listing_id, raw_data, ai_analysis):
        """
        Data Integrity: Save Raw Data to Document and AI Analysis to Sub-collection.
        """
        if not self.db:
            return False
            
        try:
            doc_ref = self.db.collection(self.collection_name).document(str(listing_id))
            
            # 1. Save Raw Data
            # Remove raw_html to avoid exceeding firestore document size limits (optional)
            data_to_save = raw_data.copy()
            if 'raw_html' in data_to_save:
                del data_to_save['raw_html']
                
            doc_ref.set(data_to_save)
            
            # 2. Save Analysis Results to Sub-collection
            analysis_ref = doc_ref.collection('Analysis_Results').document('evaluation')
            analysis_ref.set(ai_analysis)
            
            return True
        except Exception as e:
            print(f"Error saving to Firestore for ID {listing_id}: {e}")
            return False
