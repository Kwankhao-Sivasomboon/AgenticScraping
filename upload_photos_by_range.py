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

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService
from src.utils.image_processor import ImageService

# ==============================================================
# ⚙️ การตั้งค่า: ปรับได้ตามต้องการ
# ==============================================================
PROPERTY_ID_START = 1233  # api_property_id ที่เริ่มต้น
PROPERTY_ID_END   = 1448  # api_property_id ที่สิ้นสุด
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
        .where("api_property_id", ">=", PROPERTY_ID_START)
        .where("api_property_id", "<=", PROPERTY_ID_END)
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
                    valid_image_urls = [image_urls[idx] for idx in result.valid_image_indices if idx < len(image_urls)]
                    if not valid_image_urls:
                        print(f"   ⚠️ AI คัดออกหมด → ใช้รูปทั้งหมดแทน")
                        valid_image_urls = image_urls
                    print(f"   ✅ รูปที่ผ่านการคัดกรอง: {len(valid_image_urls)}/{len(image_urls)} รูป")
                    
                    # 🔥 บันทึกสีและสไตล์ที่ AI วิเคราะห์ได้ลง Firestore ทันทีเพื่อไม่ให้สูญหาย
                    if result.color_name or result.style_name:
                        update_ai_data = {}
                        if result.color_name and result.color_name not in ["", "-"]:
                            update_ai_data["color"] = result.color_name
                            print(f"   🎨 AI พบสี: {result.color_name}")
                        if result.style_name and result.style_name not in ["", "-"]:
                            update_ai_data["style"] = result.style_name
                            print(f"   🛋️ AI พบสไตล์: {result.style_name}")
                            
                        if update_ai_data:
                            firestore.db.collection(firestore.collection_name).document(listing_id).update(update_ai_data)
                            print(f"   💾 บันทึก สี/สไตล์ ลง Firestore เรียบร้อยแล้ว")
                
            except Exception as e:
                print(f"   ⚠️ AI Filtering Error: {e} → ใช้รูปทั้งหมดแทน")
                valid_image_urls = image_urls

        # โหลดและประมวลผลรูปภาพ (ลบ Watermark)
        print(f"   🖼️ กำลังโหลด {len(valid_image_urls)} รูป...")
        processed_photos = image_svc.process_images(valid_image_urls)

        if not processed_photos:
            print(f"   ❌ โหลดรูปไม่สำเร็จ ข้ามไป...")
            fail_count += 1
        else:
            print(f"   📤 กำลังอัปโหลด {len(processed_photos)} รูปเข้า API property {property_id}...")
            try:
                api.upload_photos(property_id, processed_photos)
                print(f"   ✅ อัปโหลดสำเร็จ!")
                success_count += 1
            except Exception as e:
                print(f"   ❌ Upload Error: {e}")
                fail_count += 1

        # หน่วงหลัง Upload แต่ละ Property กันถูกแบน
        import random
        sleep_time = random.uniform(DELAY_BETWEEN_UPLOADS, DELAY_BETWEEN_UPLOADS + 3.0)
        print(f"   💤 รอ {sleep_time:.1f}s ก่อนดำเนินการต่อ...")
        time.sleep(sleep_time)

    print(f"\n🎉 สรุปผล:")
    print(f"   ✅ อัปโหลดสำเร็จ : {success_count} รายการ")
    print(f"   ⏭️ ข้าม (ไม่มีรูป)  : {skip_count} รายการ")
    print(f"   ❌ ล้มเหลว         : {fail_count} รายการ")


if __name__ == "__main__":
    run_upload_photos()
