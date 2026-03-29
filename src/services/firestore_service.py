import os
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

class FirestoreService:
    def __init__(self):
        """
        Initialize connection to Google Cloud Firestore.
        Supports both Local (Credentials File) and Cloud (ADC/IAM Role) environments.
        """
        self.credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
        
        try:
            database_id = 'livinginsider-scraping'
            
            # --- 🛠️ ท่าที่ 1: ตรวจเช็คว่ามีไฟล์ Key ในเครื่องไหม (Local Mode) ---
            if self.credentials_file and os.path.exists(self.credentials_file):
                print(f"🔐 Firestore: Using local credentials file: {self.credentials_file}")
                cred = service_account.Credentials.from_service_account_file(self.credentials_file)
                self.db = firestore.Client(project=cred.project_id, credentials=cred, database=database_id)
            
            # --- 🛰️ ท่าที่ 2: ใช้ IAM Role / Application Default Credentials (Cloud Mode) ---
            else:
                print("🛰️ Firestore: No local key found. Falling back to Application Default Credentials (IAM Role).")
                # Firestore Client จะหา Project/Credential จากสถาพแวดล้อม GCP อัตโนมัติ (บน Cloud Run)
                self.db = firestore.Client(database=database_id)
                
            self.collection_name = 'Leads'
        except Exception as e:
            print(f"❌ Error initializing Firestore Client: {e}")
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
                
            # เพิ่มสถานะการซิงค์ API เข้าไปใน root document (ไว้สำหรับ Script ดึงไปทำงานต่อ)
            if 'api_synced' not in data_to_save:
                data_to_save['api_synced'] = False
                
            doc_ref.set(data_to_save, merge=True)
            
            # 2. Save Analysis Results to Sub-collection
            analysis_ref = doc_ref.collection('Analysis_Results').document('evaluation')
            analysis_ref.set(ai_analysis)
            
            return True
        except Exception as e:
            print(f"Error saving to Firestore for ID {listing_id}: {e}")
            return False

    def get_unsynced_listings(self, limit=50, zone=None, api_synced_status=False):
        """ดึงรายการตามสถานะการซิงค์ (ค่าเริ่มต้นคือดึงที่ยังไม่ซิงค์)"""
        if not self.db:
            return []
            
        try:
            # ค้นหาตามสถานะ api_synced ที่ต้องการ (True/False)
            query = self.db.collection(self.collection_name).where("api_synced", "==", api_synced_status)
            
            if zone:
                # กรองเฉพาะโซนที่ระบุ (รองรับทั้ง zone และ Zone)
                # หมายเหตุ: Firestore ปกติ query field เดียว แต่ถ้าจะเอาทั้งสองอาจต้องใช้ OR หรือ query แยก 
                # ในที่นี้ให้เน้น field "zone" เป็นหลักตามมาตรฐานใหม่
                query = query.where("zone", "==", zone)
                
            query = query.limit(limit)
            results = []
            for doc in query.stream():
                raw_data = doc.to_dict()
                listing_id = doc.id
                
                # ข้ามรายการ Legacy Import (มีแค่ URL ไม่มีข้อมูลจริง)
                if raw_data.get("status") == "legacy_import":
                    continue
                
                # ดึงข้อมูลจาก sub-collection
                analysis_doc = doc.reference.collection('Analysis_Results').document('evaluation').get()
                ai_analysis = analysis_doc.to_dict() if analysis_doc.exists else {}
                
                results.append({
                    'listing_id': listing_id,
                    'raw_data': raw_data,
                    'ai_analysis': ai_analysis
                })
            return results
        except Exception as e:
            print(f"Error fetching unsynced listings: {e}")
            return []

    def mark_as_synced(self, listing_id, api_property_id):
        """อัปเดตสถานะว่าส่งเข้า API แล้ว พร้อมแนบ ID อ้างอิง"""
        if not self.db:
            return False
            
        try:
            doc_ref = self.db.collection(self.collection_name).document(str(listing_id))
            doc_ref.update({
                'api_synced': True,
                'api_property_id': api_property_id
            })
            return True
        except Exception as e:
            print(f"Error saving to Firestore for ID {listing_id}: {e}")
            return False
