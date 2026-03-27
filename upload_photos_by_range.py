"""
Script: upload_photos_by_range.py
Description: อัปโหลดรูปภาพเข้า Production API สำหรับ Property ที่มี 
             api_property_id อยู่ใน range ที่กำหนด (เช่น 1233-1448)
             โดย:
             1. ดึง image_urls จาก Firestore
             2. ใช้ AI คัดกรองรูปภาพ (ภายใน/ภายนอก)
             3. อัปโหลดภาพ (ลบ Watermark ก่อน)
             4. ไม่แก้ไขสถานะ api_synced ใน Firestore
"""

import os
import sys
import time
import random
from datetime import datetime

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService
from google.cloud import firestore as google_firestore
from src.utils.image_processor import ImageService

# ==============================================================
# ⚙️ การตั้งค่า: ปรับได้ตามต้องการ
# ==============================================================
PROPERTY_ID_START = 1821  # api_property_id ที่เริ่มต้น
PROPERTY_ID_END   = 2175  # api_property_id ที่สิ้นสุด
SKIP_IF_PHOTOS_EXIST = True  # ถ้า True: ข้ามทรัพย์ที่ตรวจพบมีรูปใน API อยู่แล้ว 
USE_AI_FILTERING = True    # ถ้า True: ให้ AI คัดกรองรูป (ภายใน/ภายนอก) ก่อนอัปโหลด
DELAY_BETWEEN_UPLOADS = 5.0    # หน่วง (วินาที) หลังจาก Upload แต่ละ Property เสร็จ
DELAY_BETWEEN_DOWNLOADS = 1.0  # หน่วง (วินาที) ระหว่าง Download รูปแต่ละภาพ
# ==============================================================


def run_upload_photos():
    print(f"🚀 เริ่มต้น Upload Photos สำหรับ Property ID {PROPERTY_ID_START} - {PROPERTY_ID_END}...")

    firestore = FirestoreService()
    api = APIService()
    image_svc = ImageService()

    if not firestore.db:
        print("❌ เชื่อมต่อ Firestore ไม่สำเร็จ")
        return

    if not api.authenticate():
        print("❌ Login Agent API ไม่สำเร็จ")
        return

    # ดึงรายการที่มี api_property_id อยู่ใน range ที่ต้องการ
    print(f"📦 กำลังค้นหารายการใน Firestore ที่มี api_property_id = {PROPERTY_ID_START} ถึง {PROPERTY_ID_END}...")
    docs = (
        firestore.db.collection(firestore.collection_name)
        .where(filter=google_firestore.FieldFilter("api_property_id", ">=", PROPERTY_ID_START))
        .where(filter=google_firestore.FieldFilter("api_property_id", "<=", PROPERTY_ID_END))
        .stream()
    )

    target_docs = []
    for doc in docs:
        data = doc.to_dict()
        pid = data.get("api_property_id")
        images = data.get("images", [])
        if pid and images:
            target_docs.append({
                "listing_id": doc.id,
                "api_property_id": pid,
                "images": images
            })

    if not target_docs:
        print("⚠️ ไม่พบรายการที่ตรงกับเงื่อนไข (หรือไม่มีรูปภาพ)")
        return

    print(f"🔥 พบเป้าหมาย {len(target_docs)} รายการ (มีรูปภาพอยู่แล้วใน Firestore)\n")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for i, item in enumerate(target_docs, 1):
        listing_id = item["listing_id"]
        property_id = item["api_property_id"]
        image_urls = item["images"]

        print(f"\n[{i}/{len(target_docs)}] 🔄 Property ID: {property_id} (Firestore: {listing_id})")
        print(f"   📷 รูปใน Firestore: {len(image_urls)} รูป")

        valid_image_urls = image_urls

        # ให้ AI คัดกรองรูปภาพ (ภายใน/ภายนอก) ก่อนอัปโหลด
        if USE_AI_FILTERING and image_urls:
            try:
                from src.room_analyzer.style_classifier import analyze_room_images
                print(f"   🤖 [AI] กำลังคัดกรองรูป {len(image_urls)} รูป...")
                result = analyze_room_images(image_urls)
                if result:
                    # คัดเลือกเฉพาะรูปที่ AI บอกว่าผ่าน
                    valid_image_urls = [image_urls[idx] for idx in result.valid_image_indices if idx < len(image_urls)]
                    
                    if not valid_image_urls:
                        print(f"   ⚠️ AI คัดออกหมด → ใช้รูปทั้งหมดแทนเพื่อความปลอดภัย")
                        valid_image_urls = image_urls
                    else:
                        print(f"   ✅ AI คัดเหลือ: {len(valid_image_urls)}/{len(image_urls)} รูป (กำจัดรูปบอท/รูปขยะเรียบร้อย)")
                    
                    # 🔥 บันทึกสีและสไตล์ที่ AI วิเคราะห์ได้ลง Firestore
                    try:
                        update_ai_data = {}
                        if result.color_name and result.color_name not in ["", "-"]:
                            update_ai_data["color"] = result.color_name
                            print(f"   🎨 AI พบสี: {result.color_name}")
                        if result.style_name and result.style_name not in ["", "-"]:
                            update_ai_data["style"] = result.style_name
                            print(f"   🛋️ AI พบสไตล์: {result.style_name}")
                            
                        if update_ai_data:
                            firestore.db.collection(firestore.collection_name).document(listing_id).update(update_ai_data)
                            print(f"   💾 บันทึก สี/สไตล์ เรียบร้อย")
                    except Exception as fe:
                        print(f"   ⚠️ บันทึกลง Firestore ไม่สำเร็จ (แต่รูปยังกรองอยู่): {fe}")
                
            except Exception as e:
                print(f"   ⚠️ AI Filtering Logic Error: {e} → ใช้รูปทั้งหมดประคองงานไปก่อน")
                valid_image_urls = image_urls

        # โหลดและประมวลผลรูปภาพ (ลบ Watermark)
        print(f"   🖼️ กำลังโหลด {len(valid_image_urls)} รูป...")
        processed_photos = image_svc.process_images(valid_image_urls)

        if not processed_photos:
            print(f"   ❌ โหลดรูปไม่สำเร็จ ข้ามไป...")
            fail_count += 1
        else:
            max_retries = 2
            uploaded = False
            for retry in range(max_retries + 1):
                try:
                    print(f"   📤 กำลังอัปโหลด {len(processed_photos)} รูปเข้า API property {property_id}... (Attempt {retry+1})")
                    api.upload_photos(property_id, processed_photos)
                    print(f"   ✅ อัปโหลดสำเร็จ!")
                    success_count += 1
                    uploaded = True
                    break
                except Exception as e:
                    if "500" in str(e) and retry < max_retries:
                        wait = 5 * (retry + 1)
                        print(f"   ⚠️ เจอ Error 500 (Server Busy?) -> จะลองใหม่ใน {wait} วินาที...")
                        time.sleep(wait)
                    else:
                        print(f"   ❌ Upload Error: {e}")
                        fail_count += 1
                        break

        # หน่วงหลัง Upload แต่ละ Property กันถูกแบน
        sleep_time = random.uniform(1.0, 3.0)
        print(f"   💤 รอ {sleep_time:.1f}s ก่อนดำเนินการต่อ...")
        time.sleep(sleep_time)

    print(f"\n🎉 สรุปผล:")
    print(f"   ✅ อัปโหลดสำเร็จ : {success_count} รายการ")
    print(f"   ⏭️ ข้าม (ไม่มีรูป)  : {skip_count} รายการ")
    print(f"   ❌ ล้มเหลว         : {fail_count} รายการ")


if __name__ == "__main__":
    run_upload_photos()
