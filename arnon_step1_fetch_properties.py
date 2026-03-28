import os
import time
import requests
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

BASE_URL = os.getenv('AGENT_API_BASE_URL', 'http://localhost/api')

def fetch_arnon_properties_list():
    # 🚀 ปล่อยให้ APIService เลือก Email/Password จาก .env เองตามลำดับความสำคัญ
    api = APIService()
    if not api.authenticate():
        print("❌ Login failed.")
        return

    fs = FirestoreService()
    page = 1
    total_approved = 0
    total_images = 0

    print("🚀 เริ่มดึงข้อมูลจาก Agent API (ดึงทีละหน้า) เพื่อคัดกรองเฉพาะ 'Approved'...")
    
    while True:
        headers = api._get_auth_headers()
        base = BASE_URL.replace('/api', '').rstrip('/')
        url = f"{base}/api/agent/properties?page={page}"
        
        print(f"\n📄 กำลังดึงข้อมูล Page {page}...")
        res = requests.get(url, headers=headers, timeout=20)
        
        if res.status_code != 200:
            print(f"⚠️ Error: Received status code {res.status_code} at page {page}: {res.text}")
            break
            
        data = res.json()
        properties = []
        
        # ลอจิกเจาะข้อมูล (API ส่งกลับมาเป็น data -> properties หรือ list ตรงๆ)
        if isinstance(data, dict) and "data" in data:
            d1 = data["data"]
            if isinstance(d1, dict) and "properties" in d1:
                properties = d1["properties"]
            elif isinstance(d1, list):
                properties = d1
        
        if not properties:
            print(f"🏁 สิ้นสุดการค้นหา ไม่พบข้อมูลในหน้า {page} แล้ว")
            break
            
        batch = fs.db.batch()
        batch_operations_count = 0
        
        for prop in properties:
            prop_id = str(prop.get("id"))
            
            # 1. เช็ค Status 
            status_str = str(prop.get("approval_status") or "").lower()
            if "approve" not in status_str:
                continue
                
            # 2. เช็ครูปภาพ (ต้องไม่ใช่ Common facilities)
            images = prop.get("images", [])
            target_images = [img for img in images if img.get("tag") != "Common facilities"]
            
            if not target_images:
                continue
                
            print(f"   ✅ [Approved] ID: {prop_id} | รูปเป้าหมาย: {len(target_images)} รูป")
            
            # 3. ตามล่าหา Lead เดิมใน Firestore เพื่อปักธง launch_approved
            listing_id = None
            leads_docs = fs.db.collection(fs.collection_name).where(
                filter=FieldFilter("api_property_id", "==", prop_id)
            ).limit(1).get()
            
            if leads_docs:
                listing_id = leads_docs[0].id
                # ปักธงใน Lead เดิม (ทำนอก batch เพื่อป้องกัน Batch limitation ข้าม Collection)
                fs.db.collection(fs.collection_name).document(listing_id).update({
                    "launch_approved": True
                })
            
            # 4. บันทึกลงตะกร้า Launch_Properties ด้วย Batch (ห้ามใส่ analyzed/uploaded เพื่อไม่ให้ทับค่าเก่า)
            doc_ref = fs.db.collection("Launch_Properties").document(prop_id)
            batch.set(doc_ref, {
                "property_id": prop_id,
                "listing_id": listing_id,
                "images": target_images,
                "image_count": len(target_images),
                "updated_at": time.time()
            }, merge=True)
            
            batch_operations_count += 1
            total_approved += 1
            total_images += len(target_images)
            
        # Commit Batch ของหน้านี้
        if batch_operations_count > 0:
            batch.commit()
            print(f"   💾 บันทึกคิวงานหน้านี้ลง Firestore เรียบร้อยแล้ว ({batch_operations_count} รายการ)")
            
        page += 1
        time.sleep(0.5) # พักเซิร์ฟเวอร์นิดหน่อยก่อนขึ้นหน้าถัดไป

    print(f"\n🎉 ภารกิจสำเร็จ! ดึงข้อมูล Approved มาได้ทั้งหมด {total_approved} รหัสพร็อพเพอร์ตี้ (รวม {total_images} รูป)")

if __name__ == "__main__":
    fetch_arnon_properties_list()
