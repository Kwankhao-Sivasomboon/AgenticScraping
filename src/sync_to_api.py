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
from src.config import DATA_MAPPING, MAX_ITEMS_PER_RUN

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
    target_zone = "บางนา" # ระบุโซนที่ต้องการ Sync (หรือใส่ None เพื่อเอาทุกโซน)
    print(f"📦 กำลังค้นหาข้อมูลใน Firestore โซน '{target_zone}' ที่ยังไม่ได้ส่งเข้า API...")
    unsynced_listings = firestore.get_unsynced_listings(limit=MAX_ITEMS_PER_RUN, zone=target_zone, api_synced_status=True)
    
    if not unsynced_listings:
        print("✅ ไม่พบรายการที่รอการ Sync (ทุกรายการส่งขึ้น API หมดแล้ว)")
        return
        
    print(f"🔥 พบ {len(unsynced_listings)} รายการที่รอการ Sync (จำกัดครั้งละ {MAX_ITEMS_PER_RUN} รายการ)...")
    
    success_count = 0
    fail_count = 0
    
    # 3. วนลูปส่งข้อมูลตาม Field
    for item in unsynced_listings:
        listing_id = item['listing_id']
        raw_data = item['raw_data']
        ai_evaluation = item['ai_analysis']
        
        print(f"\n======================================")
        print(f"🔄 กำลังประมวลผล Listing ID: {listing_id}")
        
        # ✅ Guard: ยกเว้นรายการนำเข้าจาก Facebook (รหัสขึ้นต้นด้วย ImportSheet)
        if str(listing_id).startswith("ImportSheet"):
            print(f"⏭️ ข้าม {listing_id}: เป็นรายการนำเข้าจาก Facebook ซึ่งยังไม่มีรูประบบอัตโนมัติ")
            continue
            
        # ✅ Guard: ถ้าไม่มีข้อมูล AI Analysis (มีแค่ URL ใน Firestore) ให้ข้ามไปครับ
        if not ai_evaluation:
            print(f"⚠️ Skipping {listing_id}: ไม่มีข้อมูล AI Analysis (อาจมีแค่ URL ใน Firestore)")
            continue
            
        # ✅ Guard: ข้ามประเภททรัพย์ 'อื่นๆ' ตามที่ผู้ใช้ระบุ
        prop_type = raw_data.get("sheet_ประเภททรัพย์", "").replace(" ", "")
        if prop_type == "อื่นๆ":
            print(f"⏭️ ข้าม {listing_id}: ประเภททรัพย์ระบุว่าเป็น 'อื่นๆ'")
            # เลือกที่จะไม่เปลี่ยนเป็น Sync=True เพื่อเก็บไว้จัดการทีหลัง
            continue
        
        try:
            # ---------------------------------------------------------
            # DATA PREPARATION (แปลงข้อมูลจาก AI สู่ Payload ของ API)
            # ---------------------------------------------------------
            selected_type = ai_evaluation.get("type", "คอนโด")
            location_val = "109" if "คอนโด" in selected_type else "131" # Default to Bangkok Phattanakarn (from config)
            
            def clean(val, default=""):
                if val is None or val == "-" or str(val).strip() == "": return default
                # ตัด quote ที่อาจหลุดมาจาก JSON parsing
                return str(val).strip().strip('"')

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

            # --- AI IMAGE ANALYSIS FOR STYLE & FILTERING ---
            image_urls = raw_data.get("images", [])
            valid_image_urls = image_urls
            house_color = raw_data.get("color", "-")
            interior_style = raw_data.get("style", "-")
            
            if image_urls:
                from src.room_analyzer.style_classifier import analyze_room_images
                print(f"🤖 [AI] กำลังใช้ AI คัดกรองรูปภาพ {len(image_urls)} รูป (ภายใน/ภายนอก)...")
                analysis_result = analyze_room_images(image_urls)
                
                if analysis_result:
                    # ถ้ามี color ใน Firestore ใช้ของ Firestore ก่อน ไม่งั้นใช้ AI
                    if house_color == "-":
                        house_color = analysis_result.color_name
                    if interior_style == "-":
                        interior_style = analysis_result.interior_style  # str แล้ว ไม่ต้อง .value
                    
                    # คัดเอาเฉพาะ URL รูปภาพที่ AI บอกว่า valid (สแกนแต่พวกมุมห้อง/นอกบ้าน จริงๆ)
                    valid_image_urls = [image_urls[i] for i in analysis_result.valid_image_indices if i < len(image_urls)]
                    
                    # Fallback: ถ้า AI กรองรูปออกหมด ให้ใช้รูปทั้งหมดแทน
                    if not valid_image_urls:
                        print(f"  [AI] ⚠️ AI กรองรูปออกหมด (0 รูป) → Fallback ใช้รูปทั้งหมด {len(image_urls)} รูปแทน")
                        valid_image_urls = image_urls
                    
                    print(f"  [AI] พบรูปที่ใช้งานได้ {len(valid_image_urls)} รูป จากทั้งหมด {len(image_urls)}")
                    print(f"  [Info] สไตล์: {interior_style} | สี: {house_color}")
                    
                    # ปรับประเภททรัพย์ถ้า AI ระบุมาว่า condo หรือ house (กรณี AI ทำได้แม่นกว่า)
                    if analysis_result.property_type in ["condo", "house"] and "คอนโด" not in selected_type:
                        selected_type = analysis_result.property_type
                        
            # --- GOOGLE MAPS LOOKUP ---
            project_name = clean(ai_evaluation.get("project_name"), "-")
            
            zone_value = raw_data.get("zone") or raw_data.get("Zone") or ""
            fs_lat = clean(raw_data.get("latitude"))
            fs_lng = clean(raw_data.get("longitude"))
            fs_address = clean(raw_data.get("address"))
            
            address_data = {
                "address": fs_address if fs_address else clean(ai_evaluation.get("address"), "-"),
                "city": raw_data.get("city") or (zone_value if zone_value and zone_value != "-" else clean(ai_evaluation.get("city"), "-")),
                "state": raw_data.get("state") or clean(ai_evaluation.get("state"), "-"),
                "sub_district": raw_data.get("subdistrict") or "-",
                "postal_code": raw_data.get("postal_code") or clean(ai_evaluation.get("postal_code"), "-"),
                "country": raw_data.get("country") or "Thailand",
                "latitude": str(fs_lat) if fs_lat else str(clean(ai_evaluation.get("latitude"), "0")),
                "longitude": str(fs_lng) if fs_lng else str(clean(ai_evaluation.get("longitude"), "0"))
            }

            # พิจารณาว่าเรามีข้อมูล Location ใน Firestore มั่นคงหรือยัง (ถ้ามีแล้ว จะไม่ดึง MAPS API ใหม่อีก)
            need_map_lookup = not fs_lat or not fs_lng or str(fs_lat) in ["0", "0.0", ""]

            # เรียกดึงจาก Maps API มาทับ
            if need_map_lookup and project_name != "-":
                from src.services.maps_service import get_location_details
                map_lookup = get_location_details(project_name)
                
                # ถ้า API ได้ข้อมูลมา ให้เติมในฟิลด์ที่ขาด หรือทับค่า Default ที่ไร้ประโยชน์
                if map_lookup:
                    # รายชื่อคำที่ถือเป็น Default ภาษาอังกฤษ ให้ทับด้วยภาษาไทยจาก Maps
                    english_defaults = ["-", "0", "", "Bangkok", "Thailand", "Bangkok City", "Krung Thep Maha Nakhon", None]
                    
                    for key in ["address", "city", "state", "sub_district", "postal_code", "country", "latitude", "longitude"]:
                        if address_data.get(key) in english_defaults and map_lookup.get(key):
                            address_data[key] = map_lookup[key]

                    # นำ "ที่อยู่ภาษาไทย" จาก Maps มาเป็นฐาน (ถ้ามี) ถ้าไม่มีค่อยใช้จาก AI
                    base_address = map_lookup.get("address") if map_lookup.get("address") else clean(ai_evaluation.get("address"), "")
                    
                    # นำ แขวง/ตำบล, เขต/อำเภอ, จังหวัด เอามาต่อรวมเพิ่ม (ตามความต้องการที่ให้ใส่เพิ่ม)
                    # หมายเหตุ: แม้ใน base_address จะมีอยู่แล้ว แต่การใส่ "แขวง/ตำบล..." นำหน้าจะช่วยให้ระบบค้นหาง่ายขึ้น
                    full_addr_parts = [base_address]
                    
                    if map_lookup.get("sub_district") and map_lookup.get("sub_district") not in base_address:
                        full_addr_parts.append(f"แขวง/ตำบล {map_lookup['sub_district']}")
                    if map_lookup.get("city") and map_lookup.get("city") not in base_address:
                        full_addr_parts.append(f"เขต/อำเภอ {map_lookup['city']}")
                    if map_lookup.get("state") and map_lookup.get("state") not in base_address:
                        full_addr_parts.append(f"จังหวัด {map_lookup['state']}")
                        
                    # ต่อข้อความ โดยตัดส่วนที่ว่างทิ้ง
                    combined_address = " ".join([p for p in full_addr_parts if p.strip() and p != "-"])
                    address_data["address"] = combined_address if combined_address else "-"

            # เพิ่ม style ลงใน specifications
            if interior_style != "-":
                specs["style"] = interior_style

            # จัดการตัวเลขขนาดพื้นที่ให้สะอาดและมี Fallback (สำหรับข้อมูลเก่าที่มีแค่ size ตัวเดียว)
            def parse_float(val):
                if not val or val == "-": return 0
                val_str = str(val).replace(',', '').strip()
                return float(val_str) if val_str.replace('.', '', 1).isdigit() else 0

            b_size = parse_float(ai_evaluation.get("building_size"))
            l_size = parse_float(ai_evaluation.get("land_size"))
            legacy_size = parse_float(ai_evaluation.get("size"))

            # Fallback จากเวอร์ชันก่อนหน้าที่ AI ดึงมาแค่ "size"
            if b_size == 0 and l_size == 0 and legacy_size > 0:
                if selected_type == "condo" or "คอนโด" in selected_type:
                    b_size = legacy_size
                else:
                    l_size = legacy_size  # บ้าน มักจะบอกขนาดเป็น ตร.ว. ในช่องเก่า
                    
            # ฟิลด์ area ให้ใช้ building_size เป็นหลัก ถ้าไม่มีใช้ land_size
            final_area = b_size if b_size > 0 else l_size

            # --- OVERRIDE WITH NEW SHEET DATA (IF AVAILABLE) ---
            def get_sheet_val(key_name):
                val = raw_data.get(f"sheet_{key_name}")
                if val and str(val).strip() and str(val).strip() != "-":
                    return str(val).strip()
                return None
                
            sheet_number = get_sheet_val("เลขที่ห้อง")
            sheet_floor = get_sheet_val("ชั้น")
            sheet_phone = get_sheet_val("เบอร์โทรเจ้าของ")
            sheet_owner = get_sheet_val("ชื่อเจ้าของ")
            
            final_number = clean(sheet_number if sheet_number else ai_evaluation.get("house_number"), "-")
            final_phone = clean(sheet_phone if sheet_phone else ai_evaluation.get("phone_number"), "0")
            final_owner = clean(sheet_owner if sheet_owner else ai_evaluation.get("customer_name"), "-")
            
            if sheet_floor:
                specs["floors"] = sheet_floor

            # --- CONSTRUCT PAYLOAD ---
            payload = {
                "owner_is_agent": True,
                "living_level": clean(ai_evaluation.get("living_level"), "normal"),
                "customer_name": final_owner,
                "contact_number": final_phone,
                "line_id": clean(ai_evaluation.get("line_id"), ""),
                "area": final_area,
                "building_size": b_size if b_size > 0 else None,
                "land_size": l_size if l_size > 0 else None,

                # "direction": direction_str,  # เอาออกชั่วคราวเพราะ Validation ไม่ผ่าน
                # "furnishing": DATA_MAPPING.get("furnishings").get(ai_evaluation.get("furnishing", "ไม่ระบุ"), 4),
                "location": int(location_val), 
                "built": datetime.now().strftime("%Y-%m-%d"),
                "name": clean(ai_evaluation.get("project_name"), "-"),
                "type": "condo" if "คอนโด" in selected_type or selected_type == "condo" else "house",
                "status": "available", 
                "garage": int(specs.get("parking_spaces", 0)) if str(specs.get("parking_spaces", "0")).isdigit() else 0,
                "price": final_sell_price if final_sell_price > 0 else 0,
                "monthly_rental_price": final_rent_price if final_rent_price > 0 else 0,
                "description": "-",
                "address": address_data["address"],
                "number": final_number, 
                "city": address_data["city"],
                "state": address_data["state"],
                "district": address_data["city"],
                "province": address_data["state"],
                "subdistrict": address_data["sub_district"] if address_data["sub_district"] != "-" else None,
                "country": address_data["country"],
                "postal_code": address_data["postal_code"],
                "latitude": address_data["latitude"],
                "longitude": address_data["longitude"],
                "house_color": house_color,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "specifications": specs,
                "specification_values": ai_evaluation.get("specification_values", []),
                "property_initial_owner": final_owner if final_owner != "-" else None,
                "property_initial_owner_mobile_number": final_phone if final_phone != "0" else None,
            }

            # 4. ส่งข้อมูลเข้า Agent API สร้าง หรือ อัปเดต Property
            # สำหรับระบบ Test: เราจะมองข้าม api_property_id เดิมที่เคยได้มาจากระบบ Prod
            # แล้วบังคับให้ 'สร้างใหม่' (Create) เสมอ เพื่อให้ได้ข้อมูล lat,long,address ที่มีอยู่แล้วไปใช้ใน Test API
            
            # property_id = raw_data.get("api_property_id")
            # 
            # if property_id:
            #     # กรณีมี ID อยู่แล้ว -> สั่ง Update จบๆ
            #     print(f"🏠 [API] Updating existing property {property_id}...")
            #     success = api.update_property(property_id, payload)
            #     if not success:
            #         print(f"❌ อัปเดตล้มเหลว ข้ามไปก่อน...")
            #         fail_count += 1
            #         continue
            # else:
            
            # กรณีระบบ Test -> สั่ง Create เสมอ
            print(f"🏠 [API Test System] Forcing Create new property...")
            property_id = api.create_property(payload)
            
            if not property_id:
                print(f"⚠️ สร้างไม่สำเร็จ (อาจจะซ้ำ หรือ Error) ข้ามไปก่อน...")
                fail_count += 1
                continue
            print(f"✅ สร้างใหม่สำเร็จ! ได้ ID ใหม่จากระบบ Test: {property_id}")
            
            # 5. ซิงค์รูปภาพและลบลายน้ำ (Image Processing & Uploading)
            if valid_image_urls:
                image_svc = ImageService()
                
                print(f"🖼️ [Images] กำลังโหลดและลบลายน้ำ {len(valid_image_urls)} ภาพ...")
                processed_photos = image_svc.process_images(valid_image_urls)
                if processed_photos:
                    print(f"📤 กำลังอัปโหลดภาพเข้า Agent API...")
                    api.upload_photos(property_id, processed_photos)
                    print(f"✅ อัปโหลดภาพเสร็จสิ้น!")
                else:
                    print(f"⚠️ โหลดภาพไม่สำเร็จ ข้ามการอัปโหลด")

            # 6. อัปเดตสถานะใน Firestore ว่า Sync เสร็จแล้ว
            # เนื่องจากเป็นการยิงเข้า Test API เราจะไม่แก้ไขสถานะใดๆ ใน Database
            # if firestore.mark_as_synced(listing_id, property_id):
            #     print(f"💾 อัปเดตสถานะใน Firestore เป็น 'Synced' เรียบร้อยแล้ว")
            #     success_count += 1
            # else:
            #     print(f"⚠️ สร้างเสร็จแต่อัปเดต Firestore ไม่ได้ (โปรดระวัง Data ซ้ำในอนาคต)")
            #     fail_count += 1
            print(f"⏭️ ข้ามการบันทึก Database เพราะอยู่ในโหมด Test")
            success_count += 1
                
        except Exception as e:
            print(f"❌ Error sync สำหรับ {listing_id}: {e}")
            fail_count += 1
            
        import random
        sleep_time = random.uniform(1.0, 3.0)
        print(f"💤 Sleeping for {sleep_time:.2f}s before next listing...")
        time.sleep(sleep_time)
        
    print(f"\n🎉 สรุปผลการ Sync -> สำเร็จ: {success_count} | ล้มเหลว: {fail_count}")

if __name__ == "__main__":
    run_sync()
