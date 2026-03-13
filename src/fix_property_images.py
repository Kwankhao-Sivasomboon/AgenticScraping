import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService
from src.utils.image_processor import ImageService

def get_firestore_doc_by_api_id(firestore, api_property_id):
    """
    ค้นหารายการใน Firestore จาก api_property_id
    """
    try:
        docs = firestore.db.collection(firestore.collection_name).where("api_property_id", "==", int(api_property_id)).limit(1).get()
        if not docs:
            # Try as string if int fails
            docs = firestore.db.collection(firestore.collection_name).where("api_property_id", "==", str(api_property_id)).limit(1).get()
            
        if docs:
            doc = docs[0]
            return doc.id, doc.to_dict()
    except Exception as e:
        print(f"❌ Error searching Firestore for API ID {api_property_id}: {e}")
    return None, None

def run_fix_images():
    print("==========================================")
    print("🛠️ ระบบลบภาพเก่าและอัปโหลดภาพใหม่ (Fix Images)")
    print("==========================================")
    
    # 1. รับค่า Property IDs
    property_ids = []
    if len(sys.argv) > 1:
        # รับค่าจาก arguments (เช่น python script.py 260 261 262)
        for arg in sys.argv[1:]:
            clean_arg = arg.replace(',', '').strip()
            if clean_arg.isdigit():
                property_ids.append(int(clean_arg))
    else:
        # รับค่าจาก input (เช่น 260, 261, 262)
        raw_input = input("💬 กรุณาใส่ Property IDs ที่ต้องการแก้ไข (ใช้คอมมาแยก เช่น 260, 261): ").strip()
        if raw_input:
            parts = raw_input.split(',')
            for p in parts:
                clean_p = p.strip()
                if clean_p.isdigit():
                    property_ids.append(int(clean_p))
        
    if not property_ids:
        print("❌ ไม่พบ Property ID ที่ถูกต้อง")
        return
        
    print(f"✅ เตรียมจัดการทั้งหมด {len(property_ids)} รายการ: {property_ids}")

    # 2. เริ่มเชื่อมต่อบริการต่างๆ (ทำครั้งเดียวที่ต้นสคริปต์)
    print("\n🔗 กำลังเชื่อมต่อระบบ...")
    api = APIService()
    if not api.authenticate():
        print("❌ ไม่สามารถ Login เข้า Agent API ได้")
        return

    firestore = FirestoreService()
    if not firestore.db:
        print("❌ ไม่สามารถเชื่อมต่อ Firestore ได้")
        return
        
    img_service = ImageService()

    # 3. วนลูปจัดการทีละ Property
    for idx, property_id_int in enumerate(property_ids, 1):
        print(f"\n[{idx}/{len(property_ids)}] 🔄 กำลังเริ่มแก้ไข Property ID: {property_id_int}")
        print("-" * 40)

        # A. GET Status เพื่อดึง Image IDs ปัจจุบัน
        status_data = api.get_property_status(property_id_int)
        if not status_data or not status_data.get('success'):
            print(f"❌ ไม่สามารถดึงสถานะของ Property {property_id_int} ได้ ข้าม...")
            continue
            
        images = status_data.get('data', {}).get('images', [])
        print(f"📸 พบรูปภาพเดิมบนระบบทั้งหมด {len(images)} รูป")

        # B. ลบรูปเดิมออกทั้งหมด
        if len(images) > 0:
            print(f"🗑️ กำลังลบรูปภาพเดิมทั้งหมด...")
            for img in images:
                img_id = img.get('id')
                if img_id:
                    api.delete_property_image(property_id_int, img_id)
                    time.sleep(0.5) # หน่วงเวลานิดหน่อย
        else:
            print(f"ℹ️ ไม่มีรูปภาพเดิมให้ลบ")

        # C. หาข้อมูล Original จาก Firestore
        print(f"🔍 ค้นหาข้อมูลต้นฉบับใน Firestore...")
        listing_id, raw_data = get_firestore_doc_by_api_id(firestore, property_id_int)
        
        if not raw_data:
            print(f"❌ ไม่พบข้อมูลใน Firestore ของ API ID: {property_id_int} ข้าม...")
            continue
            
        original_images = raw_data.get("images", [])
        if isinstance(original_images, str):
            original_images = [original_images]
            
        if not original_images:
            print(f"❌ ไม่พบรูปภาพต้นฉบับ (URLs) ให้ดึงใหม่ ข้าม...")
            continue
            
        print(f"📦 พบรูปภาพต้นฉบับ {len(original_images)} รูป")

        # D. ดึงรูปและใช้งาน ImageService
        print("🪄 ดาวน์โหลดและจัดการรูปภาพ...")
        memory_files = img_service.process_images(original_images)
        
        if not memory_files:
            print("❌ โหลดภาพต้นฉบับล้มเหลว ข้าม...")
            continue

        # E. อัปโหลดรูปใหม่
        print(f"🚀 อัปโหลดรูปภาพใหม่ {len(memory_files)} รูป...")
        success = api.upload_photos(property_id_int, memory_files)
        
        if success:
            print(f"✅ แก้ไข Property ID: {property_id_int} เสร็จสมบูรณ์")
        else:
            print(f"❌ อัปโหลดไม่สำเร็จสำหรับ Property ID: {property_id_int}")

        # หน่วงเวลาสั้นๆ ก่อนไปตัวถัดไป
        if idx < len(property_ids):
            print("\n💤 รอสักครู่ก่อนเริ่มรายการถัดไป...")
            time.sleep(3)

    print("\n" + "="*40)
    print(f"🏁 เสร็จสิ้นการซ่อมแซมรูปภาพทั้งหมด {len(property_ids)} รายการ")
    print("="*40)

if __name__ == "__main__":
    run_fix_images()
