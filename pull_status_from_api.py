"""
Script: pull_status_from_api.py
Description: ดึงข้อมูลล่าสุดจาก Agent API (เช่น address, location, color, style) 
เพื่อนำมาเซฟลงใน Firestore ป้องกันไม่ให้ AI ต้องประมวลผลข้อมูลเหล่านี้ซ้ำอีกในอนาคต
"""

import time
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

def run_pull_status():
    print("🚀 เริ่มต้นดึงข้อมูล Status (Location, Color, Style) จาก Agent API คืนสู่ Firestore...")
    
    firestore = FirestoreService()
    api = APIService()
    
    if not firestore.db:
        print("❌ เชื่อมต่อ Firestore ไม่สำเร็จ")
        return
        
    if not api.authenticate():
        print("❌ Login Agent API ไม่สำเร็จ")
        return
        
    print("📦 กำลังค้นหารายการที่มี api_property_id ใน Firestore...")
    
    # หารายการทั้งหมดที่มี api_property_id อยู่แล้ว (แปลว่าซิงค์ไปแล้วหรือมีอยู่แล้วบน API)
    # หมายเหตุ: .stream() เฉยๆ อาจจะกวาดข้อมูลมาเยอะ แต่อันนี้จำเป็นเพื่อเช็ค property_id
    docs = firestore.db.collection(firestore.collection_name).where("api_property_id", "!=", None).stream()
    
    target_docs = []
    for doc in docs:
        data = doc.to_dict()
        api_property_id = data.get("api_property_id")
        if api_property_id:
            target_docs.append({'id': doc.id, 'api_property_id': api_property_id, 'data': data})
            
    if not target_docs:
        print("✅ ไม่พบรายการที่มี api_property_id")
        return
        
    print(f"🔥 พบเป้าหมายทั้งหมด {len(target_docs)} รายการ")
    
    success_count = 0
    fail_count = 0
    
    # Fields ที่เราต้องการจะ Update กลับลงไป
    fields_to_sync = [
        "latitude", "longitude", "city", "state", "district", "province", 
        "subdistrict", "country", "postal_code", "address", "color", "style"
    ]
    
    for i, item in enumerate(target_docs, 1):
        doc_id = item['id']
        property_id = item['api_property_id']
        old_data = item['data']
        
        print(f"\n[{i}/{len(target_docs)}] 🔄 กำลังดึงข้อมูล Property ID: {property_id} (Firestore ID: {doc_id})")
        
        # ดึงสถานะปัจจุบันจาก API
        api_data = api.get_property_status(property_id)
        
        if not api_data:
            print(f"⚠️ ไม่สามารถดึงข้อมูลจาก API ได้ ข้ามไปก่อน...")
            fail_count += 1
            continue
            
        update_payload = {}
        
        # 1. ดึงข้อมูลจากส่วน location
        api_location = api_data.get('location', {})
        loc_fields = ["latitude", "longitude", "city", "state", "district", "province", "subdistrict", "country", "postal_code"]
        for field in loc_fields:
            val = api_location.get(field)
            if val is not None and val != "" and old_data.get(field) != val:
                update_payload[field] = val
                
        # 2. ดึงข้อมูลจากส่วน specs
        api_specs = api_data.get('specs', {})
        
        # ดึง address
        addr = api_specs.get('address')
        if addr and old_data.get('address') != addr:
            update_payload['address'] = addr
            
        # ดึง color (ใน API คือ house_color)
        color = api_specs.get('house_color')
        if color and old_data.get('color') != color:
            update_payload['color'] = color
            
        # ดึง style (ถ้ามีในอนาคต หรือเก็บไว้ก่อน)
        style = api_specs.get('style') # ปัจจุบันใน JSON ยังไม่มี แต่ใส่เผื่อไว้ตาม request
        if style and old_data.get('style') != style:
            update_payload['style'] = style
                    
        if update_payload:
            print(f"📝 พบข้อมูลที่ต้องอัปเดต ({len(update_payload)} fields): {list(update_payload.keys())}")
            try:
                # แก้ไขค่าใน Firestore (รวมถึงอัปเดตสถานะว่าดึง api_status แล้วเผื่อลูปหน้า)
                update_payload['last_status_pull'] = time.time()
                firestore.db.collection(firestore.collection_name).document(doc_id).update(update_payload)
                print(f"💾 บันทึกการอัปเดตสำเร็จ!")
                success_count += 1
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดในการบันทึก Firestore: {e}")
                fail_count += 1
        else:
            print(f"✅ ข้อมูลครบถ้วนอยู่แล้ว หรือไม่มีอะไรใหม่อัปเดตบน API")
            
        # พักเล็กน้อยป้องกันการรัว API เกินไป
        time.sleep(0.5)
        
    print(f"\n🎉 สรุปผล: อัปเดตข้อมูลสำเร็จ {success_count} รายการ | ล้มเหลว/ข้าม {fail_count} รายการ")

if __name__ == "__main__":
    run_pull_status()
