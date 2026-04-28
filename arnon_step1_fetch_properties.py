import os
import time
import requests
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

TARGET_COLLECTION = "area_color"

def fetch_and_save_properties(api: APIService, fs: FirestoreService, account_name: str):
    page = 1
    total_approved = 0
    total_images = 0
    
    email = api.email
    print(f"\n🚀 เริ่มดึงข้อมูลบัญชี: {account_name} ({email})")
    
    while True:
        headers = api._get_auth_headers()
        base = api.base_url.replace('/api', '').rstrip('/')
        url = f"{base}/api/agent/properties?page={page}"
        
        print(f"📄 Page {page}...")
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code != 200:
                print(f"⚠️ Error {res.status_code} at page {page}")
                break
                
            data = res.json()
            properties = []
            if isinstance(data, dict) and "data" in data:
                d1 = data["data"]
                if isinstance(d1, dict) and "properties" in d1:
                    properties = d1["properties"]
                elif isinstance(d1, list):
                    properties = d1
            
            if not properties:
                print(f"🏁 สิ้นสุดข้อมูลที่หน้า {page-1}")
                break
                
            batch = fs.db.batch()
            batch_count = 0
            
            for prop in properties:
                prop_id = str(prop.get("id"))
                status_str = str(prop.get("approval_status") or "").lower()
                if "approve" not in status_str:
                    continue
                    
                images = prop.get("images", [])
                target_images = [img for img in images if img.get("tag") != "Common facilities"]
                if not target_images:
                    continue
                    
                print(f"   ✅ [Approved] ID: {prop_id} ({len(target_images)} images)")
                
                # หา Lead เดิม
                listing_id = None
                leads_docs = fs.db.collection(fs.collection_name).where(
                    filter=FieldFilter("api_property_id", "==", prop_id)
                ).limit(1).get()
                
                if leads_docs:
                    listing_id = leads_docs[0].id
                    fs.db.collection(fs.collection_name).document(listing_id).update({"launch_approved": True})
                
                # บันทึกลงตะกร้า
                doc_ref = fs.db.collection(TARGET_COLLECTION).document(prop_id)
                batch.set(doc_ref, {
                    "property_id": prop_id,
                    "listing_id": listing_id,
                    "images": target_images,
                    "image_count": len(target_images),
                    "fetch_email": email, # 🚩 ปักธง Email ที่ดึงมา
                    "updated_at": time.time()
                }, merge=True)
                
                batch_count += 1
                total_approved += 1
                total_images += len(target_images)
            
            if batch_count > 0:
                batch.commit()
            
            page += 1
            time.sleep(0.5) # ป้องกัน Rate limit
            
        except Exception as e:
            print(f"❌ Error at page {page}: {e}")
            break

    print(f"🏁 สำเร็จ! บัญชี {account_name}: ดึงได้ {total_approved} Approved Properties ({total_images} รูป)")

if __name__ == "__main__":
    fs = FirestoreService()
    
    # 1. รอบ Automation
    api_auto = APIService()
    if api_auto.authenticate():
        fetch_and_save_properties(api_auto, fs, "Automation")
    
    # 2. รอบ Arnon
    api_arnon = APIService()
    if api_arnon.authenticate(use_arnon=True):
        fetch_and_save_properties(api_arnon, fs, "Arnon")
