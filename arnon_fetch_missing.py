import os
import time
import random
import requests
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

def fetch_approved_properties():
    fs = FirestoreService()
    api = APIService() 
    api.authenticate()
    
    print("🚀 เริ่มดึงข้อมูล Lead จาก Firestore ที่อัปโหลดไปแล้ว (api_synced=True)...")
    
    # 1. เริ่มดูที่ firestore lead เพื่อดู property_id (ใช้ get() แทน stream() เพื่อความเสถียร)
    leads_docs = fs.db.collection(fs.collection_name).where(filter=FieldFilter("api_synced", "==", True)).get()
    
    headers = api._get_auth_headers()
    base_url = api.base_url.rstrip('/')
    
    for doc in leads_docs:
        lead_data = doc.to_dict()
        pid = lead_data.get("api_property_id")
        listing_id = doc.id
        
        if not pid:
            continue
            
        print(f"\n🔍 Inspecting ID {pid} (Listing: {listing_id})")
        
        # 2. get ข้อมูลแบบรวบยอด (มีทั้ง Status และ รูปภาพ)
        detail_endpoint = f"{base_url}/api/agent/properties/{pid}"
        
        is_approved = False
        target_images = []
        
        try:
            r_detail = requests.get(detail_endpoint, headers=headers, timeout=15)
            if r_detail.status_code == 200:
                full_json = r_detail.json()
                prop_data = full_json.get("data", {})
                if not isinstance(prop_data, dict): prop_data = {}
                
                # 🎯 เช็คสถานะ Approved ทันทีจาก Response ก้อนเดียวกัน
                status_str = str(prop_data.get("approval_status") or full_json.get("approval_status") or "").lower()
                
                if "approve" in status_str:
                    is_approved = True
                    print("   ✅ สถานะ 'Approved'! กำลังสกัดข้อมูลรูปภาพ (ยกเว้น Common facilities)...")
                    
                    # ลองดึง images ออกมาจากหลายมุมกระเป๋า (เผื่อโครงสร้างขยับ)
                    images = prop_data.get("images", [])
                    if not images and isinstance(prop_data.get("property"), dict):
                        images = prop_data.get("property", {}).get("images", [])
                    if not images:
                        images = full_json.get("images", [])
                    
                    if images:
                        target_images = [img for img in images if img.get("tag") != "Common facilities"]
        except Exception as e:
            print(f"   ⚠️ Error fetch property {pid}: {e}")
            
        if not is_approved:
            print("   ⏭️ ไม่ใช่ 'Approved' ข้าม...")
        elif target_images:
            print(f"   📸 พบรูปภาพเป้าหมายจำนวน {len(target_images)} รูป")
            
            # 3. (ต่อ) ใส่หัวข้อใน lead ว่า launch_approved = True
            fs.db.collection(fs.collection_name).document(listing_id).update({
                "launch_approved": True
            })
            
            # 4. บันทึกลงตะกร้า Launch_Properties (ห้ามใส่ analyzed/uploaded เพื่อไม่ให้ทับค่าเก่า)
            launch_ref = fs.db.collection("Launch_Properties").document(str(pid))
            launch_ref.set({
                "property_id": str(pid),
                "listing_id": listing_id,
                "images": target_images,
                "image_count": len(target_images),
                "updated_at": time.time()
            }, merge=True)
            print(f"   💾 บันทึก ID {pid} ลงตะกร้า 'Launch_Properties' เรียบร้อยแล้ว")
        else:
            print(f"   ⚠️ ข้าม: ไม่มีภาพเป้าหมายเลย หลังจากตัด Common facilities ออก")
            
        # ⏱️ [DELAY] พักหายใจเพื่อไม่ให้เป็นภาระเซิร์ฟเวอร์ ป้องกัน 500 / SSL Timeout
        delay = random.uniform(1.8, 3.5)
        print(f"   ⏳ รอ {delay:.1f} วินาทีก่อนไปรายการถัดไป...")
        time.sleep(delay)

if __name__ == "__main__":
    fetch_approved_properties()
