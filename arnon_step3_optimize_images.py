import os
import io
import requests
import time
import sys
import argparse
from PIL import Image
from dotenv import load_dotenv

# นำเข้า Service ที่มีอยู่แล้วในโปรเจกต์
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

BASE_URL = os.getenv('AGENT_API_BASE_URL', 'https://dev.yourhome.co.th/api')

def optimize_to_webp(image_bytes, quality=85):
    """
    แปลงรูปภาพเป็น Webp ด้วย quality 85
    """
    img = Image.open(io.BytesIO(image_bytes))
    
    # หากมีช่อง Alpha ให้แปลงเพื่อความชัวร์
    if img.mode in ("P", "RGBA"):
        img = img.convert("RGBA")
    elif img.mode != "RGB":
        img = img.convert("RGB")
        
    out_io = io.BytesIO()
    img.save(out_io, format="WEBP", quality=quality)
    return out_io.getvalue()

def process_property(property_id, api, headers, base):
    """
    ฟังก์ชันหลักสำหรับประมวลผล Property ทีละรหัส
    """
    print(f"\n🚀 เริ่มประมวลผล Property ID: {property_id}")
    
    # 1. Get status เพื่อหารูปภาพเดิม
    status_url = f"{base}/api/agent/properties/{property_id}/status"
    res_status = requests.get(status_url, headers=headers)
    
    if res_status.status_code != 200:
        print(f"⚠️ ไม่พบข้อมูล Property หรือเข้าไม่ถึง status (Status: {res_status.status_code})")
        print(f"   Response: {res_status.text}")
        return False
            
    status_data = res_status.json()
    raw_images = []
    if isinstance(status_data, dict) and "data" in status_data:
        raw_images = status_data["data"].get("images", [])
            
    if not raw_images:
        print(f"   ℹ️ ไม่มีรูปภาพใน Property นี้")
        return False

    # --- ใหม่: ขั้นตอนการ Refresh Photo URLs เพื่อกัน URL หมดอายุ ---
    all_image_ids = [img_obj.get('id') for img_obj in raw_images if img_obj.get('id')]
    if all_image_ids:
        print(f"   🔄 กำลัง Refresh URL สำหรับ {len(all_image_ids)} รูป...")
        refresh_url = f"{base}/api/agent/refresh/photo-urls"
        try:
            refresh_res = requests.post(refresh_url, headers=headers, json={"image_ids": all_image_ids}, timeout=20)
            if refresh_res.status_code == 200:
                refresh_data = refresh_res.json()
                
                # --- แก้ไบ: ลอจิกการแกะข้อมูลให้ถูกชั้นเหมือน step 2 ---
                # โครงสร้างน่าจะเป็น {"success": true, "data": {"refreshed_images": [...]}}
                data_part = refresh_data.get('data', {})
                if isinstance(data_part, dict):
                    refreshed_list = data_part.get('refreshed_images', [])
                else:
                    # กรณีเป็น list ตรงๆ (Fallback)
                    refreshed_list = data_part if isinstance(data_part, list) else []
                
                # สร้าง Map ของ ID -> URL ใหม่
                url_map = {str(item.get('id')): item.get('url') for item in refreshed_list if item.get('id') and item.get('url')}
                
                # อัปเดต URL ใน raw_images
                for img_obj in raw_images:
                    img_id = str(img_obj.get('id'))
                    if img_id in url_map:
                        img_obj['url'] = url_map[img_id]
                print(f"      ✅ Refresh URL สำเร็จ")
            else:
                print(f"      ⚠️ Refresh URL ไม่สำเร็จ (Status: {refresh_res.status_code}) จะลองใช้ URL เดิม...")
        except Exception as e:
            print(f"      ⚠️ เกิดข้อผิดพลาดขณะ Refresh URL: {e}")

    upload_payload_data = {'property_id': property_id}
    upload_payload_files = []
    old_image_ids = []

    print(f"   📸 พบรูปภาพทั้งหมด {len(raw_images)} รูป กำลังประมวลผลเป็น WebP...")

    # 2. จัดการแปลงรูปทุกรูป (Sequential indexing: photos[0], photos[1]...)
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
            # ดาวน์โหลดรูป (ใช้ URL ที่ Refresh แล้ว)
            img_res = requests.get(img_url, timeout=20)
            if img_res.status_code != 200:
                print(f"      ❌ โหลดไม่สำเร็จ: {img_id}")
                continue
            
            # แปลงเป็น WebP
            optimized_webp = optimize_to_webp(img_res.content, quality=85)
            
            img_tag = img_obj.get('tag') or 'gallery'
            upload_payload_files.append({
                'file_tuple': (f"opt_{img_id}.webp", optimized_webp, 'image/webp'),
                'tag': img_tag
            })
            
            old_image_ids.append(img_id)
            print(f"      🪄 แปลงรูป {img_id} สำเร็จ ({len(img_res.content)/1024:.1f}KB -> {len(optimized_webp)/1024:.1f}KB) [Tag: {img_tag}]")
            process_idx += 1
            
        except Exception as e:
            print(f"      ❌ มีเงื่อนไขผิดปกติที่รูป {img_id}: {e}")

    # 3. อัปโหลดรูปทีละชุด (Batch of 100) เพื่อกัน Server 500 error
    if not upload_payload_files:
        print(f"   ℹ️ ไม่มีรูปใหม่ที่ต้องอัปโหลด")
        return False

    batch_size = 100
    upload_url = f"{base}/api/agent/upload/photos"
    print(f"   📤 กำลังอัปโหลดรูปแบบ Batch ย่อย (ชุดละ {batch_size} รูป)...")
    
    all_upload_success = True
    for i in range(0, len(upload_payload_files), batch_size):
        chunk_files = upload_payload_files[i:i + batch_size]
        
        # สำคัญ: ห้ามมี Content-Type ใน Header สำหรับ Multipart Upload
        # เพราะ requests จะสร้าง boundary ให้เองโดยอัตโนมัติ
        up_headers = headers.copy()
        if "Content-Type" in up_headers:
            del up_headers["Content-Type"]
        up_headers["User-Agent"] = "PostmanRuntime/7.26.8" # เลียนแบบ Postman
        up_headers["Accept"] = "application/json"

        # ปรับ Payload Index ให้เริ่มจาก 0 สำหรับแต่ละ Request
        chunk_payload_data = {'property_id': str(property_id).strip()} # ส่งเป็น String ตาม Postman
        chunk_files_payload = []
        
        for idx, item in enumerate(chunk_files):
            new_prefix = f"photos[{idx}]"
            chunk_files_payload.append((f"{new_prefix}[file]", item['file_tuple']))
            chunk_payload_data[f"{new_prefix}[tag]"] = item['tag']

        print(f"      📦 กำลังส่งชุดที่ {(i // batch_size) + 1} ({len(chunk_files)} รูป)...")
        
        try:
            up_res = requests.post(upload_url, headers=up_headers, data=chunk_payload_data, files=chunk_files_payload, timeout=60)
            
            if up_res.status_code in (200, 201):
                print(f"      ✅ ชุดที่ {(i // batch_size) + 1} สำเร็จ!")
            else:
                print(f"      ❌ ชุดที่ {(i // batch_size) + 1} ผิดพลาด: {up_res.status_code}")
                print(f"         📜 Response: {up_res.text}")
                all_upload_success = False
                break # หยุดการอัปโหลดถ้าพังชุดนึง

            # หน่วงเวลาสั้นๆ ระหว่าง Batch
            if i + batch_size < len(upload_payload_files):
                time.sleep(1.5)
                
        except Exception as e:
            print(f"      ❌ Network Error ในชุดนี้: {e}")
            all_upload_success = False
            break

    # 4. ลบรูปเดิมทิ้งแบบ Bulk Cleanup (ทำเฉพาะเมื่ออัปโหลดทุกชุดสำเร็จ)
    if all_upload_success and old_image_ids:
        del_url = f"{base}/api/agent/properties/{property_id}/images/delete"
        del_headers = headers.copy()
        del_headers['Content-Type'] = 'application/json'
        del_payload = {"image_ids": old_image_ids}
        
        print(f"   🗑️ กำลังส่งคำสั่งลบรูปภาพเก่าจำนวน {len(old_image_ids)} รูป...")
        del_res = requests.post(del_url, headers=del_headers, json=del_payload)
        
        if del_res.status_code in (200, 201):
            print(f"      ✅ ลบรูปเดิมทั้งหมดสำเร็จแล้ว")
        else:
            print(f"      ⚠️ ลบรูปเดิมไม่สำเร็จ: {del_res.status_code} - {del_res.text}")
        return True
    return False

def main():
    # Setup Argument Parser สำหรับโหมดทดสอบ
    parser = argparse.ArgumentParser(description='Optimize property images to WebP')
    parser.add_argument('--id', type=str, help='Specific Property ID to process (Test Mode)')
    args = parser.parse_args()

    api = APIService()
    if not api.authenticate():
        print("❌ Login failed.")
        return

    # สร้าง headers พื้นฐานพร้อม Accept: application/json
    headers = api._get_auth_headers()
    headers['Accept'] = 'application/json'
    
    base = BASE_URL.replace('/api', '').rstrip('/')

    if args.id:
        # โหมดรันทดสอบทีละ ID
        print(f"🛠️ [Test Mode] รันเฉพาะ Property ID: {args.id}")
        process_property(args.id, api, headers, base)
    else:
        # โหมดรันปกติจาก Firestore
        fs = FirestoreService()
        collection_name = 'Leads' 
        print(f"🔍 Fetching properties from Firestore ({collection_name})...")
        
        docs = fs.db.collection(collection_name).limit(3000).stream() 
        
        for doc in docs:
            data = doc.to_dict()
            property_id = data.get('api_property_id') or data.get('property_id') or doc.id
            
            # กรองเฉพาะที่เป็นรหัสตัวเลข (ถ้าไม่ระบุ ID เฉพาะ)
            if not str(property_id).isdigit():
                continue
                
            process_property(property_id, api, headers, base)

if __name__ == "__main__":
    main()
