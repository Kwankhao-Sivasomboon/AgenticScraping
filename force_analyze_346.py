
import os
import sys
import time
import random

# Setup Root Path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.room_analyzer.style_classifier import analyze_room_images

def force_analyze_properties(target_ids):
    fs = FirestoreService()
    
    print(f"🚀 เริ่มต้นการวิเคราะห์ใหม่ (Force Analyze) สำหรับ {len(target_ids)} รายการ...")
    
    success_count = 0
    fail_count = 0

    for idx, api_id in enumerate(target_ids, 1):
        print(f"\n[{idx}/{len(target_ids)}] 🔄 กำลังวิเคราะห์ ID: {api_id}...")
        
        try:
            # 1. ค้นหา Listing ใน Firestore โดยใช้ api_property_id
            query = fs.db.collection(fs.collection_name).where("api_property_id", "in", [int(api_id), str(api_id)]).limit(1).get()
            if not query:
                # ลองค้นหาด้วย Document ID เผื่อกรณีพิเศษ
                doc = fs.db.collection(fs.collection_name).document(str(api_id)).get()
                if not doc.exists:
                    print(f"   ❌ ไม่พบ ID {api_id} ใน Firestore")
                    fail_count += 1
                    continue
                target_doc = doc
            else:
                target_doc = query[0]
            
            listing_id = target_doc.id
            raw_data = target_doc.to_dict() # [FIX] เพิ่มการประกาศตัวแปร raw_data
            
            # 2. กวาดรูปภาพทั้งหมด (จากทั้ง Sub-collection และ Root List)
            image_urls = []
            
            # แบบที่ 1: จากฟิลด์ 'images' ใน Root (List of strings)
            root_images = raw_data.get("images")
            if isinstance(root_images, list):
                for url in root_images:
                    if isinstance(url, str) and url.startswith("http"):
                        image_urls.append(url)
            
            # แบบที่ 2: จาก Sub-collection 'Images' (เผื่อกรณีดึงงานเก่า)
            images_ref = target_doc.reference.collection('Images').get()
            for img_doc in images_ref:
                url = img_doc.to_dict().get("url")
                if url and url not in image_urls:
                    image_urls.append(url)
            
            # แบบที่ 3: เช็ค 'image_url' (ถ้ามีแค่รูปเดียว)
            if not image_urls and raw_data.get("image_url"):
                image_urls.append(raw_data.get("image_url"))
            
            if not image_urls:
                print(f"   ⚠️ ไม่พบรูปภาพสำหรับ {listing_id}")
                fail_count += 1
                continue
            
            print(f"   📸 พบรูปภาพ {len(image_urls)} รูป กำลังส่งให้ Gemini...")

            # 3. ส่งให้ AI วิเคราะห์ (ใช้ฟังก์ชัน analyze_room_images ตรงๆ)
            analysis_result = analyze_room_images(image_urls)
            
            if not analysis_result:
                print(f"   ❌ AI วิเคราะห์ไม่สำเร็จ")
                fail_count += 1
                continue

            # 4. แปลง Furniture เป็น string สำหรับ Firestore (Array of List)
            raw_furniture = analysis_result.element_furniture
            furniture_storage = [", ".join(items) if items else "" for items in raw_furniture]

            # 5. อัปเดตข้อมูลกลับเข้า Firestore Document หลัก
            update_payload = {
                "room_color": analysis_result.room_color,
                "element_color": analysis_result.element_color,
                "element_furniture": furniture_storage,
                "interior_style": analysis_result.interior_style,
                "last_force_analyze_at": time.time(),
                "is_new_sheet": True # เพื่อให้ตัว Sync กวาดไปลง API ด้วย
            }
            
            target_doc.reference.update(update_payload)
            print(f"   ✅ วิเคราะห์สำเร็จ! (Style: {analysis_result.interior_style}, Color: {analysis_result.color})")
            success_count += 1
            
            # รอนิดนึงกันโดนบล็อก
            time.sleep(random.uniform(1.0, 2.0))

        except Exception as e:
            print(f"   ❌ เกิดข้อผิดพลาด: {str(e)}")
            fail_count += 1

    print("\n" + "="*40)
    print(f"🏁 การวิเคราะห์เสร็จสิ้น!")
    print(f"✅ สำเร็จ: {success_count} | ❌ ล้มเหลว: {fail_count}")
    print("="*40)

if __name__ == "__main__":
    # ลิสต์ ID ที่บอสต้องการ (Zero Color + 100% White)
    default_ids = [347, 368, 1977, 1199, 707, 928, 754, 948, 1083, 851, 781, 805, 1351, 1224, 1389]
    
    # ถ้าระบุ ID ผ่าน command line ให้รันแค่ตัวนั้น
    if len(sys.argv) > 1:
        target_ids = [sys.argv[1]]
    else:
        target_ids = default_ids

    force_analyze_properties(target_ids)
