import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

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
            return doc.reference, doc.id, doc.to_dict()
    except Exception as e:
        print(f"❌ Error searching Firestore for API ID {api_property_id}: {e}")
    return None, None, None

def run_sync_location():
    print("==========================================")
    print("🌍 ระบบดึงที่อยู่จาก Agent API กลับมาเก็บใน Firestore")
    print("==========================================")
    
    firestore = FirestoreService()
    if not firestore.db:
        print("❌ ไม่สามารถเชื่อมต่อ Firestore ได้")
        return
        
    api = APIService()
    
    # 1. รับค่า Property IDs หรือดึงทั้งหมด
    property_ids = []
    if len(sys.argv) > 1:
        if sys.argv[1].lower() == '--all':
            print("🔍 กำลังค้นหา Property ID ทั้งหมดใน Firestore ที่ api_synced = True ...")
            try:
                # Firestore query needs caution with indexes, but streaming should be fine
                docs = firestore.db.collection(firestore.collection_name).where("api_synced", "==", True).stream()
                for doc in docs:
                    data = doc.to_dict()
                    if data.get("api_property_id"):
                        property_ids.append(int(data.get("api_property_id")))
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดในการดึงข้อมูลจาก Firestore: {e}")
                return
        else:
            for arg in sys.argv[1:]:
                clean_arg = arg.replace(',', '').strip()
                if clean_arg.isdigit():
                    property_ids.append(int(clean_arg))
    else:
        raw_input = input("💬 กรุณาใส่ Property IDs (ใช้คอมมาแยก เช่น 320, 321) หรือพิมพ์ 'all' เพื่อดึงทั้งหมด: ").strip()
        if raw_input.lower() == 'all':
            print("🔍 กำลังค้นหา Property ID ทั้งหมดใน Firestore ที่ api_synced = True ...")
            try:
                docs = firestore.db.collection(firestore.collection_name).where("api_synced", "==", True).stream()
                for doc in docs:
                    data = doc.to_dict()
                    if data.get("api_property_id"):
                        property_ids.append(int(data.get("api_property_id")))
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดในการดึงข้อมูลจาก Firestore: {e}")
                return
        elif raw_input:
            parts = raw_input.split(',')
            for p in parts:
                clean_p = p.strip()
                if clean_p.isdigit():
                    property_ids.append(int(clean_p))
        
    # Remove duplicates
    property_ids = list(set(property_ids))
        
    if not property_ids:
        print("❌ ไม่พบ Property ID ให้ดำเนินการ")
        return
        
    print(f"✅ เตรียมอัปเดตข้อมูลสถานที่ทั้งหมด {len(property_ids)} รายการ")

    # 2. เริ่มเชื่อมต่อ API
    print("\n🔗 กำลัง Login Agent API...")
    if not api.authenticate():
        print("❌ ไม่สามารถ Login เข้า Agent API ได้")
        return

    success_count = 0
    fail_count = 0

    # 3. วนลูปจัดการทีละ Property
    for idx, property_id_int in enumerate(property_ids, 1):
        print(f"\n[{idx}/{len(property_ids)}] 🔄 กำลังดึงข้อมูล Property ID: {property_id_int}")
        
        doc_ref, listing_id, raw_data = get_firestore_doc_by_api_id(firestore, property_id_int)
        if not doc_ref:
            print(f"⚠️ ไม่พบ Property ID {property_id_int} ใน Firestore สคิปข้าม...")
            fail_count += 1
            continue

        status_data = api.get_property_status(property_id_int)
        if not status_data or not status_data.get('success'):
            print(f"❌ ไม่สามารถดึงสถานะจาก API ได้ ข้าม...")
            fail_count += 1
            continue
            
        data_block = status_data.get('data', {})
        location_data = data_block.get('location')
        
        if not location_data:
            print(f"⚠️ Property ID {property_id_int} ไม่มีข้อมูล location ใน API ข้าม...")
            fail_count += 1
            continue

        print("📍 พบข้อมูล Location เตรียมอัปเดตลง Firestore...")
        
        # จัดเตรียมฟิลด์ที่จะเขียนลง Firestore 
        update_payload = {
            "api_location_city": location_data.get("city"),
            "api_location_state": location_data.get("state"),
            "api_location_district": location_data.get("district"),
            "api_location_province": location_data.get("province"),
            "api_location_country": location_data.get("country"),
            "api_location_postal_code": location_data.get("postal_code"),
            "api_location_lat": location_data.get("latitude"),
            "api_location_lng": location_data.get("longitude"),
        }
        
        # กรองเอาเฉพาะข้อมูลที่มีค่าจริงๆ (ไม่เป็น None หรือว่างเปล่าเกินไป)
        update_payload = {k: v for k, v in update_payload.items() if v is not None}
        
        # เก็บที่อยู่แบบรวบยอด (จากหมวด specs.address ถ้ามี)
        if data_block.get("specs") and data_block.get("specs").get("address"):
            update_payload["api_address"] = data_block.get("specs").get("address")

        try:
            doc_ref.set(update_payload, merge=True)
            print(f"✅ อัปเดต Firestore [{listing_id}] เรียบร้อย!")
            success_count += 1
        except Exception as e:
            print(f"❌ บันทึก Firestore ล้มเหลว: {e}")
            fail_count += 1

        if idx < len(property_ids):
            time.sleep(1) # หน่วงเวลา

    print("\n" + "="*40)
    print(f"🏁 เสร็จสิ้นการอัปเดตสถานที่! (สำเร็จ: {success_count}, ล้มเหลว/ข้าม: {fail_count})")
    print("="*40)

if __name__ == "__main__":
    run_sync_location()
