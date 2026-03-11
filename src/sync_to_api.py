import os
import sys
import time
from datetime import datetime

# ย้าย Path เพื่อให้เรียกใช้ src.services ได้จากโฟลเดอร์ root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService
from src.utils.image_processor import ImageService
from src.config import DATA_MAPPING

def run_sync():
    print("🚀 เริ่มต้นกระบวนการ Sync ข้อมูลจาก Firestore ไปยัง Agent API...")
    
    # กำหนด Services
    firestore = FirestoreService()
    api = APIService()
    image_svc = ImageService()
    
    # 1. Login เข้า Agent API
    if not api.authenticate():
        print("❌ Login Agent API ล้มเหลว! ยกเลิกการ Sync")
        return
        
    # 2. ดึงข้อมูลที่ยังไม่ได้ Sync
    print("📦 กำลังค้นหาข้อมูลใน Firestore ที่ยังไม่ได้ส่งเข้า API...")
    unsynced_listings = firestore.get_unsynced_listings(limit=1) # ทดสอบเพียง 1 รายการตามคำขอ
    
    if not unsynced_listings:
        print("✅ ไม่พบรายการที่รอการ Sync (ทุกรายการส่งขึ้น API หมดแล้ว)")
        return
        
    print(f"🔥 พบ {len(unsynced_listings)} รายการที่รอการ Sync (จะทดสอบ 1 รายการ)...")
    
    success_count = 0
    fail_count = 0
    
    # 3. วนลูปส่งข้อมูลตาม Field
    for item in unsynced_listings:
        listing_id = item['listing_id']
        raw_data = item['raw_data']
        ai_evaluation = item['ai_analysis']
        
        print(f"\n======================================")
        print(f"🔄 กำลังประมวลผล Listing ID: {listing_id}")
        
        try:
            # ---------------------------------------------------------
            # DATA PREPARATION (แปลงข้อมูลจาก AI สู่ Payload ของ API)
            # ---------------------------------------------------------
            selected_type = ai_evaluation.get("type", "คอนโด")
            location_val = "109" if "คอนโด" in selected_type else "131" # Default to Bangkok Phattanakarn (from config)
            
            # Helper: แปลง None (null), "-" หรือค่าว่าง ให้เป็นค่าที่ API ต้องการ
            def clean(val, default=""):
                if val is None or val == "-": return default
                return val

            # เช็คและแปลงราคา
            def parse_final_price(val):
                if isinstance(val, (int, float)): return float(val)
                if isinstance(val, str):
                    p_str = val.replace(',', '').replace(' ', '')
                    numbers = re.findall(r'(\d+\.?\d*)', p_str)
                    if numbers: return float(numbers[0])
                return 0

            # Import re here for safety
            import re
            final_sell_price = parse_final_price(ai_evaluation.get("price_sell", 0))
            final_rent_price = parse_final_price(ai_evaluation.get("price_rent", 0))

            # แยกห้องนอนห้องน้ำสำหรับ Agent API
            specs = ai_evaluation.get("specifications", {})
            bedrooms = int(specs.get("bedrooms", 13)) if specs.get("bedrooms") else 13 # 13 คือ "ไม่ระบุ" ใน mapping ตระกูลห้อง
            bathrooms = int(specs.get("bathrooms", 13)) if specs.get("bathrooms") else 13

            # --- CONSTRUCT PAYLOAD ---
            payload = {
                "owner_is_agent": True,
                "living_level": "normal",
                "customer_name": clean(ai_evaluation.get("customer_name"), "Owner (LivingInsider)"),
                "contact_number": clean(ai_evaluation.get("phone_number")),
                "line_id": clean(ai_evaluation.get("line_id")),
                "area": float(ai_evaluation.get("size", 0)) if str(ai_evaluation.get("size", "0")).replace('.','',1).isdigit() else 0,
                "direction": DATA_MAPPING.get("directions").get(ai_evaluation.get("direction", "ไม่ระบุทิศ"), 8),
                "furnishing": DATA_MAPPING.get("furnishings").get(ai_evaluation.get("furnishing", "ไม่ระบุ"), 4),
                "location": int(location_val), 
                "built": datetime.now().strftime("%Y-%m-%d"),
                "name": clean(ai_evaluation.get("project_name"), f"Listing {listing_id}"),
                "type": "condo" if "คอนโด" in selected_type else "house",
                "status": "pending", 
                "price": final_sell_price if final_sell_price > 0 else 0,
                "monthly_rental_price": final_rent_price if final_rent_price > 0 else 0,
                "description": clean(raw_data.get("raw_text"), "")[:4000], 
                "address": clean(ai_evaluation.get("address"), ""),
                "number": clean(ai_evaluation.get("house_number"), ""),
                "city": clean(ai_evaluation.get("city"), ""),
                "postal_code": clean(ai_evaluation.get("postal_code"), ""),
                "latitude": str(clean(ai_evaluation.get("latitude"), "")),
                "longitude": str(clean(ai_evaluation.get("longitude"), "")),
                "bedroom": bedrooms,
                "bathroom": bathrooms,
                "specifications": specs,
                "specification_values": ai_evaluation.get("specification_values", {})
            }

            # 4. ส่งข้อมูลเข้า Agent API สร้าง Property
            print(f"🏠 [API] Creating property (Status: PENDING) in Agent API...")
            property_id = api.create_property(payload)
            
            if not property_id:
                print(f"❌ ล้มเหลวในการสร้าง Property บน API สำหรับ ID: {listing_id}")
                fail_count += 1
                continue
                
            print(f"✅ สร้าง Property สำเร็จ! (API Property ID: {property_id})")
            
            # 5. ซิงค์รูปภาพและลบลายน้ำ (Image Processing & Uploading)
            image_urls = raw_data.get("images", [])
            if image_urls:
                print(f"🖼️ [Images] กำลังโหลดและลบลายน้ำ {len(image_urls)} ภาพ...")
                processed_photos = image_svc.process_images(image_urls)
                if processed_photos:
                    print(f"📤 กำลังอัปโหลดภาพเข้า Agent API...")
                    api.upload_photos(property_id, processed_photos)
                    print(f"✅ อัปโหลดภาพเสร็จสิ้น!")
                else:
                    print(f"⚠️ โหลดภาพไม่สำเร็จ ข้ามการอัปโหลด")

            # 6. อัปเดตสถานะใน Firestore ว่า Sync เสร็จแล้ว
            if firestore.mark_as_synced(listing_id, property_id):
                print(f"💾 อัปเดตสถานะใน Firestore เป็น 'Synced' เรียบร้อยแล้ว")
                success_count += 1
            else:
                print(f"⚠️ สร้างเสร็จแต่อัปเดต Firestore ไม่ได้ (โปรดระวัง Data ซ้ำในอนาคต)")
                fail_count += 1
                
        except Exception as e:
            print(f"❌ Error sync สำหรับ {listing_id}: {e}")
            fail_count += 1
            
        time.sleep(2) # กัน API เตะออกเพราะยิงถี่เกิน
        
    print(f"\n🎉 สรุปผลการ Sync -> สำเร็จ: {success_count} | ล้มเหลว: {fail_count}")

if __name__ == "__main__":
    run_sync()
