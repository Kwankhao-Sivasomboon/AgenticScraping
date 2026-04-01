import os
import io
import requests
import time
from PIL import Image
from dotenv import load_dotenv

# นำเข้า Service ที่มีอยู่แล้วในโปรเจกต์
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

BASE_URL = os.getenv('AGENT_API_BASE_URL', 'https://dev.yourhome.co.th/api')

def optimize_to_webp(image_bytes, quality=85):
    """
    แปลงรูปภาพเป็น Webp ด้วย quality 85 ตามแผนเดิม
    """
    img = Image.open(io.BytesIO(image_bytes))
    
    # หากมีช่อง Alpha ให้แปลงเพื่อความชัวร์ (หรือรักษาก็ได้ถ้าเป็น PNG)
    if img.mode in ("P", "RGBA"):
        img = img.convert("RGBA")
    elif img.mode != "RGB":
        img = img.convert("RGB")
        
    out_io = io.BytesIO()
    img.save(out_io, format="WEBP", quality=quality)
    return out_io.getvalue()

def process_and_optimize_images():
    api = APIService()
    if not api.authenticate():
        print("❌ Login failed.")
        return

    fs = FirestoreService()
    
    # ดึงจาก Leads (แหล่งข้อมูลที่คุณระบุ)
    collection_name = 'Leads' 
    print(f"🔍 Fetching properties from Firestore ({collection_name})...")
    
    # ดึงมาประมวลผล 100 รายการ เพื่อหา Property ที่มีข้อมูลในระบบจริง
    docs = fs.db.collection(collection_name).limit(100).stream() 
    
    headers = api._get_auth_headers()
    base = BASE_URL.replace('/api', '').rstrip('/')
    
    for doc in docs:
        data = doc.to_dict()
        # พยายามเอารหัส property_id ที่เป็นตัวเลขจริง
        # กรองเฉพาะรหัสเดิมที่เป็น numeric
        property_id = data.get('api_property_id') or data.get('property_id') or doc.id
        
        if not str(property_id).isdigit():
            # ค้นหาในฟิลด์อื่นๆ เผื่อมีรหัสตัวเลขซ่อนอยู่
            found_id = None
            for key in ['id', 'listing_id', 'property_id']:
                val = data.get(key)
                if val and str(val).isdigit():
                    found_id = str(val)
                    break
            if not found_id:
                continue
            property_id = found_id

        print(f"\n🚀 เริ่มประมวลผล Property ID: {property_id}")
        
        # 1. Get status เพื่อหารูปภาพเดิม
        status_url = f"{base}/api/agent/properties/{property_id}/status"
        res_status = requests.get(status_url, headers=headers)
        if res_status.status_code != 200:
            print(f"⚠️ ไม่พบข้อมูล Property หรือเข้าไม่ถึง status (Status: {res_status.status_code})")
            continue
            
        status_data = res_status.json()
        raw_images = []
        if isinstance(status_data, dict) and "data" in status_data:
            raw_images = status_data["data"].get("images", [])
            
        if not raw_images:
            print(f"ℹ️ ไม่มีรูปภาพใน Property นี้")
            continue

        upload_payload_data = {'property_id': property_id}
        upload_payload_files = []
        old_image_ids = []

        print(f"   📸 พบรูปภาพทั้งหมด {len(raw_images)} รูป กำลังแปลงเป็น WebP...")

        # 2. จัดการแปลงรูปทุกรูป (Sequential indexing hance 0, 1, 2...)
        process_idx = 0
        for img_obj in raw_images:
            img_id = img_obj.get('id')
            img_url = img_obj.get('url')
            
            if not img_id or not img_url: continue
            
            # ข้ามถ้ารูปเป็น webp อยู่แล้ว
            if img_url.lower().split('?')[0].endswith('.webp'):
                print(f"      ✅ รูป {img_id} เป็น WebP อยู่แล้ว ข้าม...")
                continue
            
            try:
                # ดาวน์โหลดรูป
                img_res = requests.get(img_url, timeout=20)
                if img_res.status_code != 200:
                    print(f"      ❌ โหลดไม่สำเร็จ: {img_id}")
                    continue
                
                # แปลงเป็น WebP
                optimized_webp = optimize_to_webp(img_res.content, quality=85)
                
                # Payload แบบ Array: photos[n][file] / photos[n][tag]
                file_key = f"photos[{process_idx}][file]"
                tag_key = f"photos[{process_idx}][tag]"
                
                upload_payload_files.append((file_key, (f"opt_{img_id}.webp", optimized_webp, 'image/webp')))
                upload_payload_data[tag_key] = 'gallery' 
                
                old_image_ids.append(img_id)
                print(f"      🪄 แปลงรูป {img_id} สำเร็จ ({len(img_res.content)/1024:.1f}KB -> {len(optimized_webp)/1024:.1f}KB)")
                process_idx += 1
                
            except Exception as e:
                print(f"      ❌ มีเงื่อนไขผิดปกติที่รูป {img_id}: {e}")

        # 3. อัปโหลดรูปทั้งหมดทีเดียว
        if not upload_payload_files:
            continue

        upload_url = f"{base}/api/agent/upload/photos"
        print(f"   📤 กำลัง Batch Upload รูปใหม่จำนวน {len(upload_payload_files)} รูป...")
        
        try:
            # ส่งเป็น Multipart/form-data
            up_res = requests.post(upload_url, headers=headers, data=upload_payload_data, files=upload_payload_files)
            
            if up_res.status_code in (200, 201):
                print(f"   ✨ อัปโหลด WebP สำเร็จ!")
                
                # 4. ลบรูปภาพ ID เดิมทิ้ง (Cleanup)
                for old_id in old_image_ids:
                    del_url = f"{base}/api/agent/properties/{property_id}/images/{old_id}/delete"
                    del_res = requests.post(del_url, headers=headers)
                    if del_res.status_code == 200:
                        print(f"      🗑️ ลบรูปเดิม ID: {old_id} สำเร็จ")
                    else:
                        print(f"      ⚠️ ลบรูปเดิม ID: {old_id} ไม่สำเร็จ: {del_res.status_code}")
            else:
                print(f"   ❌ อัปโหลดผิดพลาด: {up_res.status_code}")
                # Log Response Body เผื่อใช้ debug error 500 จากหลังบ้าน
                print(f"      📜 Response: {up_res.text}")
                
        except Exception as e:
            print(f"   ❌ Network Error: {e}")

if __name__ == "__main__":
    process_and_optimize_images()
