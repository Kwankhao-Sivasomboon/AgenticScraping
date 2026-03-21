"""
Script: sync_new_sheet_to_api.py
Description: อัปเดตข้อมูลที่เป็น status: new_sheet จาก Firestore ไปยัง Agent API
             โดยเน้นข้อมูลใหม่จาก Google Sheet เป็น First Priority 
             ประกอบด้วยการ Update Property และ Log Activities (Calls, Accept, Deny)
"""

import os
import sys
import time
from datetime import datetime

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

# จำกัดจำนวนเพื่อความปลอดภัย
MAX_ITEMS_PER_RUN = 1

def clean(text, default=""):
    if not text or str(text).strip() == "":
        return default
    return str(text).strip()

def parse_float(val):
    if not val or str(val).strip() in ["-", ""]: return None
    v_str = str(val).replace(',', '').strip()
    try:
        return float(v_str)
    except ValueError:
        return None

def parse_beds_baths(val):
    if not val or str(val).strip() in ["-", ""]: return None
    try:
        num = int(float(str(val).strip()))
        if num == 13: return None
        if num == 14: return 1
        return num
    except ValueError:
        return None

def run_sync_new_sheet():
    print(f"🚀 เริ่มต้นกระบวนการ Sync ข้อมูล 'new_sheet' ไปยัง Agent API...")
    
    firestore = FirestoreService()
    api = APIService()
    
    if not firestore.db:
        print("❌ เชื่อมต่อ Firestore ไม่สำเร็จ")
        return
        
    if not api.authenticate():
        print("❌ Login Agent API ล้มเหลว! ยกเลิกการ Sync")
        return

    print("📦 กำลังค้นหาข้อมูลใน Firestore ที่มี status = 'new_sheet'...")
    # Firestore ไม่รองรับ 'not starts with' ดึงมาก่อนแล้ว Filter เอง
    # ใช้ buffer ขนาดใหญ่พอเพื่อกันกรณีที่มี ImportSheet เยอะ
    query_limit = MAX_ITEMS_PER_RUN + 200
    query = firestore.db.collection(firestore.collection_name).where("status", "==", "new_sheet").limit(query_limit)
    docs = query.stream()

    items_to_sync = []
    import_sheet_skipped = 0
    for doc in docs:
        listing_id = doc.id
        # กรอง ImportSheet ออกตั้งแต่ตอนโหลด
        if listing_id.startswith("ImportSheet"):
            import_sheet_skipped += 1
            continue
        
        raw_data = doc.to_dict()
        
        # กรองทรัพย์ประเภท "อื่นๆ" ออก (เช่น ที่ดิน, โกดัง ที่ไม่ได้รองรับ)
        property_type_sheet = clean(raw_data.get("sheet_ประเภททรัพย์"))
        if property_type_sheet == "อื่นๆ":
            # เปลี่ยนสถานะใน Firestore เป็น ignored เพื่อไม่ให้ query ติดซ้ำๆ (ถ้าต้องการ) หรือแค่ข้ามไป
            # firestore.db.collection(firestore.collection_name).document(listing_id).update({"status": "ignored"})
            print(f"   ⏭️ ข้าม Listing {listing_id} (ประเภททรัพย์: อื่นๆ)")
            continue

        # ดึง ai_analysis จาก subcollection เผื่อต้องใช้ข้อมูล fallback
        analysis_doc = doc.reference.collection('Analysis_Results').document('evaluation').get()
        ai_evaluation = analysis_doc.to_dict() if analysis_doc.exists else {}
        
        items_to_sync.append({
            'listing_id': listing_id,
            'raw_data': raw_data,
            'ai_evaluation': ai_evaluation
        })
        
        if len(items_to_sync) >= MAX_ITEMS_PER_RUN:
            break

    if import_sheet_skipped > 0:
        print(f"   ⏭️ ข้ามรายการ ImportSheet: {import_sheet_skipped} รายการ")

    if not items_to_sync:
        print("✅ ไม่พบข้อมูล new_sheet ที่รอการ Sync (นอกจาก ImportSheet)")
        return

    print(f"🔥 พบ {len(items_to_sync)} รายการที่รอการอัปเดต...")

    success_count = 0
    fail_count = 0

    for item in items_to_sync:
        listing_id = item['listing_id']
        raw_data = item['raw_data']
        ai_evaluation = item.get('ai_evaluation', {})
        
        print(f"\n======================================")
        print(f"🔄 กำลังประมวลผล Listing ID: {listing_id}")

        # === เตรียมคำนวณ Field ===
        
        # 1. Status (sheet_อยู่ไหม)
        sheet_still_there = clean(raw_data.get("sheet_อยู่ไหม"))
        status_val = "available"
        if sheet_still_there == "ยังอยู่":
            status_val = "available"
        elif sheet_still_there == "ปล่อยแล้ว":
            status_val = "sold"
        elif sheet_still_there in ["ไม่ทราบ", "ติดผู้เช่า"]:
            status_val = "unavailable"

        # 2. Reference URL (sheet_ลิงค์/url)
        sheet_url = clean(raw_data.get("sheet_ลิงค์/url"))
        reference_url = sheet_url if sheet_url and sheet_url != "-" else None

        # 3. Property Visit (sheet_เข้าดูห้อง, sheet_สแกน)
        sheet_visit = clean(raw_data.get("sheet_เข้าดูห้อง"))
        sheet_scan = clean(raw_data.get("sheet_สแกน"))
        
        property_visit = None
        if sheet_visit == "อนุญาตให้เข้า":
            if sheet_scan == "อนุญาต":
                property_visit = "Visit&Scan"
            elif sheet_scan == "ไม่สะดวก":
                property_visit = "Visit"
        elif sheet_visit == "ไม่สะดวก":
            property_visit = "Deny"

        # 4. Sizes (sheet_Area (M), sheet_Area (W))
        b_size = parse_float(raw_data.get("sheet_Area (M)"))
        l_size = parse_float(raw_data.get("sheet_Area (W)"))
        
        if b_size is None and l_size is None:
            # Fallback จาก ai_evaluation
            legacy_size = parse_float(ai_evaluation.get("size"))
            selected_type = clean(raw_data.get("sheet_ประเภททรัพย์"))
            if legacy_size:
                if "คอนโด" in selected_type or selected_type == "condo":
                    b_size = legacy_size
                else:
                    l_size = legacy_size
                    
        final_area = b_size if b_size is not None else (l_size if l_size is not None else 0)

        # 5. Beds / Baths (13 -> null, 14 -> 1)
        bedrooms = parse_beds_baths(raw_data.get("sheet_Bed"))
        if bedrooms is None: bedrooms = parse_beds_baths(ai_evaluation.get("bedrooms"))
        if bedrooms is None: bedrooms = 0  # ต้องไม่เป็น None เพื่อผ่าน API Validation
        
        bathrooms = parse_beds_baths(raw_data.get("sheet_Bath"))
        if bathrooms is None: bathrooms = parse_beds_baths(ai_evaluation.get("bathrooms"))
        if bathrooms is None: bathrooms = 0  # ต้องไม่เป็น None เพื่อผ่าน API Validation

        # --- Base Data Fallbacks ---
        zone_name_fallback = firestore.collection_name.replace("Properties_", "")
        zone_name = clean(raw_data.get("zone")) or clean(raw_data.get("Zone")) or zone_name_fallback
        
        selected_type = clean(raw_data.get("sheet_ประเภททรัพย์"), "condo")
        prop_type = "condo" if "คอนโด" in selected_type or selected_type == "condo" else "house"
        
        final_number = clean(raw_data.get("sheet_เลขที่ห้อง") or ai_evaluation.get("house_number"), "-")
        final_phone = clean(raw_data.get("sheet_เบอร์โทรเจ้าของ") or ai_evaluation.get("phone_number"), "0")
        final_owner = clean(raw_data.get("sheet_ชื่อเจ้าของ") or ai_evaluation.get("customer_name"), "-")
        
        # ดึงราคา (รองรับทั้งชื่อภาษาไทยและอังกฤษจาก Sheet)
        rent_raw = raw_data.get("sheet_ราคาเช่า") or raw_data.get("sheet_Price  (Rent)") or ai_evaluation.get("rental_price")
        sell_raw = raw_data.get("sheet_ราคาขาย") or raw_data.get("sheet_Price (Sell)") or ai_evaluation.get("sell_price")

        # ฟังก์ชันช่วยล้าง ฿ และ , ออกก่อแปลงเลข
        def clean_price(val):
            if not val: return "0"
            return str(val).replace("฿", "").replace(",", "").strip()

        rent_price = parse_float(clean_price(rent_raw)) or 0
        sell_price = parse_float(clean_price(sell_raw)) or 0

        address = clean(raw_data.get("address")) or clean(ai_evaluation.get("address")) or "-"
        
        # --- กำหนด Payload ตรงตาม Postman ล่าสุด ---
        payload = {
            "property_initial_owner": final_owner,
            "property_initial_owner_mobile_number": final_phone,
            "building_size": b_size,
            "land_size": l_size,
            "built": datetime.now().strftime("%Y-%m-%d"),
            "name": clean(ai_evaluation.get("project_name"), "-"),
            "type": prop_type,
            "status": status_val, 
            "price": sell_price,
            "monthly_rental_price": rent_price,
            "description": "-",
            "address": address,
            "number": final_number, 
            "city": clean(raw_data.get("city"), zone_name),
            "state": clean(raw_data.get("state"), "กรุงเทพมหานคร"),
            "district": clean(raw_data.get("city"), zone_name),
            "province": clean(raw_data.get("state"), "กรุงเทพมหานคร"),
            "subdistrict": clean(raw_data.get("subdistrict"), "-"),
            "country": clean(raw_data.get("country"), "Thailand"),
            "postal_code": clean(raw_data.get("postal_code"), "-"),
            "house_color": clean(raw_data.get("color"), "-"),
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "garage": 0,
            "reference_url": reference_url,
            "property_visit": property_visit
        }
        # ใส่ latitude/longitude เฉพาะตอนมีค่า
        # ถ้าไม่มีค่า หรือ city, state เป็น "-" → ให้เรียก Maps API โดยอัตโนมัติ
        lat_val = parse_float(raw_data.get("latitude"))
        lng_val = parse_float(raw_data.get("longitude"))

        if lat_val is None or lng_val is None or payload["city"] == "-" or payload["state"] == "-":
            project_name_for_map = clean(ai_evaluation.get("project_name")) or clean(raw_data.get("name"))
            if project_name_for_map and project_name_for_map != "-":
                print(f"   🗺️ ไม่มีพิกัด/ที่อยู่ → เรียก Maps API ด้วยชื่อ: '{project_name_for_map}'")
                from src.services.maps_service import get_location_details
                map_result = get_location_details(project_name_for_map)
                if map_result:
                    lat_val = parse_float(map_result.get("latitude")) if lat_val is None else lat_val
                    lng_val = parse_float(map_result.get("longitude")) if lng_val is None else lng_val
                    # ถ้า payload ยังไม่มีที่อยู่ ให้ใช้จาก Maps ด้วย
                    if payload["address"] == "-":
                        payload["address"] = map_result.get("address", "-")
                    if payload["city"] == "-" or payload["city"] == zone_name:
                        payload["city"] = map_result.get("city", zone_name)
                        payload["district"] = map_result.get("city", zone_name)
                    if payload["state"] == "-" or payload["state"] == "กรุงเทพมหานคร":
                        payload["state"] = map_result.get("state", "กรุงเทพมหานคร")
                        payload["province"] = map_result.get("state", "กรุงเทพมหานคร")
                    if payload["subdistrict"] == "-":
                        payload["subdistrict"] = map_result.get("sub_district", "-")
                    if payload["postal_code"] == "-":
                        payload["postal_code"] = map_result.get("postal_code", "-")
                    print(f"   ✅ Maps API ได้พิกัดและที่อยู่ใหม่")
            else:
                print(f"   ⚠️ ไม่มีข้อมูลพิกัดและไม่มีชื่อโครงการ → ข้ามการเรียก Maps API")

        if lat_val is not None: payload["latitude"] = lat_val
        if lng_val is not None: payload["longitude"] = lng_val

        # ก่อนส่ง API ต้องบังคับให้ field สำคัญไม่เป็นค่าว่าง ("") เด็ดขาด
        for key in ["city", "state", "district", "province", "subdistrict", "postal_code", "address", "name"]:
            if not payload.get(key) or str(payload.get(key)).strip() == "":
                payload[key] = "-"

        property_id = raw_data.get("api_property_id")
        
        if property_id:
            # Update Existing
            print(f"🏠 [API] Updating property {property_id}...")
            # ดึง response มาตรวจสอบเผื่อพังเพราะ 403
            try:
                api_success = api.update_property(property_id, payload)
            except Exception as e:
                # ถ้าพังเพราะ 403 (Forbidden) แสดงว่าไม่ใช่ของเจ้าของนี้ ให้ลอง Create ใหม่แทน
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 403:
                    print(f"   ⚠️ ติด 403 (No Access) → ลอง Create ใหม่แทน...")
                    property_id = api.create_property(payload)
                    api_success = True if property_id else False
                else:
                    api_success = False
        else:
            # Create New
            print(f"🏠 [API] Creating new property...")
            property_id = api.create_property(payload)
            api_success = True if property_id else False

        if not api_success or not property_id:
            print(f"❌ Failed to sync Property (Create/Update failed).")
            fail_count += 1
            continue
            
        # ถ้า Create ใหม่สำเร็จ ให้เซฟ Property ID ลง Firestore เผื่อไว้ใช้ด้วย
        if not raw_data.get("api_property_id"):
            firestore.db.collection(firestore.collection_name).document(listing_id).update({"api_property_id": property_id})

        # ==========================================
        # 6. สร้าง Activity (Call, Accept, Deny)
        # ==========================================
        sheet_call_status = clean(raw_data.get("sheet_สถานะการโทร"))
        sheet_market_status = clean(raw_data.get("sheet_ขอทำการตลาด"))
        sheet_contact_latest = clean(raw_data.get("sheet_ติดต่อล่าสุด"))
        sheet_feedback = clean(raw_data.get("sheet_Feedback"))
        sheet_remark = clean(raw_data.get("sheet_Remark"))

        activities = []
        
        def parse_date_to_ymd(date_str):
            if not date_str or date_str == "-": return None
            # ล้าง string เผื่อมี space หน้า/หลัง
            ds = str(date_str).strip()
            # อาจจะมีเวลาติดมา ให้ตัดทิ้ง ลองใช้ regex หรือ split
            ds = ds.split(" ")[0].split("T")[0] 

            # ไล่ตรวจสอบ Format ยอดฮิตที่อาจจะเจอ
            formats = [
                "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
                "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%y", "%m/%d/%y"
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(ds, fmt)
                    # ถ้าเจอ format ที่รอด ให้ return เป็น YYYY-MM-DD ตามที่ Postman บังคับ
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
            # คืน None หากแปลงไม่ได้ จะได้ไม่เสี่ยงร่วงตอน API ส่ง 500
            return None

        # --- 6.1 Call Activity ---
        call_outcome = None
        call_notes_parts = []
        if sheet_feedback and sheet_feedback != "-": call_notes_parts.append(f"Feedback: {sheet_feedback}")
        if sheet_remark and sheet_remark != "-": call_notes_parts.append(f"Remark: {sheet_remark}")
        notes_str = "\n".join(call_notes_parts)

        # Mapping โทษการโทร
        if sheet_call_status == "ติดต่อแล้ว":
            call_outcome = "reached"
        elif sheet_call_status == "ไม่รับสาย":
            call_outcome = "no_answer"
        elif sheet_call_status == "ให้โทรกลับ":
            call_outcome = "callback_later"
        elif sheet_call_status == "ติดต่อไม่ได้":
            call_outcome = "wrong_number"
        elif sheet_call_status.lower() == "line":
            call_outcome = "other"
            notes_str = f"Line | {notes_str}".strip()

        # กรณี "โทรติด AGENT" สามารถ Override ลงไปได้
        if sheet_market_status == "โทรติด AGENT":
            call_outcome = "other"
            notes_str = f"โทรติด AGENT | {notes_str}".strip()

        notes_str = notes_str.replace("\n", " | ")

        if call_outcome:
            call_payload = {
                "type": "call",
                "call_outcome": call_outcome
            }
            # Clean notes: จำกัดความยาวและตัดอักขระแปลกๆ
            if notes_str: 
                call_payload["notes"] = notes_str[:500] 
            
            # ดึงกำหนดติดตามผลครั้งต่อไป (Next Follow Up At)
            formatted_date = parse_date_to_ymd(sheet_contact_latest)
            if formatted_date:
                call_payload["next_follow_up_at"] = formatted_date
                
            activities.append(call_payload)

        # --- 6.2 Accept/Deny Activity ---
        if sheet_market_status in ["อนุญาต", "ติดผู้เช่า"]:
            activities.append({
                "type": "accept",
                "reason": "Owner agreed to agent representation."
            })
        elif sheet_market_status in ["ไม่สะดวก", "โทรติด AGENT", "ติดต่อไม่ได้"]:
            activities.append({
                "type": "deny",
                "reason": "Owner decided to list without agent."
            })

        # Submit Activities
        print(f"   ℹ️ จำนวน Activity ที่จะถูกส่ง: {len(activities)} รายการ")
        if len(activities) > 0:
            import time
            time.sleep(1) # เพิ่ม Delay เพื่อป้องกัน DB หลังบ้าน Transaction หลุด (Race Condition)
            
        for act_payload in activities:
            print(f"   ► ส่ง Activity: {act_payload}")
            api.create_activity(property_id, act_payload)

        # Update status completed
        # เราตั้งสถานะให้ api_synced = True หรือจะเปลี่ยน status ด้วยก็ได้
        firestore.db.collection(firestore.collection_name).document(listing_id).update({
            "api_synced": True,
            # บางทีอาจจะอยากให้แก้ไข field 'status' กลับเป็นอย่างอื่น ถ้าต้องการลบสถานะ new_sheet
            # "status": "processed" 
        })
        
        print(f"✅ Sync ข้อมูล Listing {listing_id} เสร็จสิ้น")
        success_count += 1
        
        time.sleep(1)

    print(f"\n🎉 สรุปผล Sync New Sheet: สำเร็จ {success_count} | ล้มเหลว {fail_count}")

if __name__ == "__main__":
    run_sync_new_sheet()
