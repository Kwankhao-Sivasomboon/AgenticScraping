import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService
from src.config import DATA_MAPPING

def clean(val, default):
    if not val or val == "Not Specified" or val == "-" or str(val).strip() == "":
        return default
    return str(val).strip()

def run_update_batch():
    print("🚀 เริ่มต้นกระบวนการ Batch Update ซ่อมแซมข้อมูล Property ID 320 - 739...")
    
    load_dotenv()
    firestore = FirestoreService()
    api = APIService()
    
    if not firestore.db:
        print("❌ เชื่อมต่อ Firestore ไม่สำเร็จ")
        return
        
    if not api.authenticate():
        print("❌ Login Agent API ล้มเหลว! ยกเลิกการ Batch Update")
        return
        
    print("📦 กำลังโหลดข้อมูลจาก Firestore...")
    # โหลด Lead ทั้งหมดที่ซิงค์แล้ว เพื่อมาหา api_property_id 320-739
    # (ใช้ query ดึงทั้งหมดแล้วค่อย loop กรองเพื่อความชัวร์ เพราะ type ของ api_property_id อาจจะเป็น int หรือ str)
    query = firestore.db.collection(firestore.collection_name).where("api_synced", "==", True).stream()
    
    target_docs = []
    for doc in query:
        data = doc.to_dict()
        pid = data.get("api_property_id")
        
        if pid is not None:
            try:
                pid_int = int(pid)
                if 321 <= pid_int <= 739:
                    target_docs.append((doc.id, data, pid_int))
            except ValueError:
                pass
                
    print(f"🔥 พบ {len(target_docs)} รายการที่ตรงเงื่อนไข Property ID 321 - 739")
    
    success_count = 0
    fail_count = 0
    
    for listing_id, raw_data, property_id in sorted(target_docs, key=lambda x: x[2]):
        print(f"\n======================================")
        print(f"🔄 กำลังจัดการ Property ID: {property_id} (Listing: {listing_id})")
        
        # ดึง Analysis Results จาก sub-collection
        analysis_doc = firestore.db.collection(firestore.collection_name).document(listing_id).collection('Analysis_Results').document('evaluation').get()
        ai_evaluation = analysis_doc.to_dict() if analysis_doc.exists else {}
        
        if not ai_evaluation:
            print(f"⚠️ ข้าม: ไม่พบ ai_analysis สำหรับ {listing_id}")
            continue
            
        # --- 1. จัดการข้อมูลขนาด ---
        def parse_float(val):
            if not val or val == "-": return 0
            val_str = str(val).replace(',', '').strip()
            return float(val_str) if val_str.replace('.', '', 1).isdigit() else 0
            
        selected_type = ai_evaluation.get("type", "คอนโด")
        b_size = parse_float(ai_evaluation.get("building_size"))
        l_size = parse_float(ai_evaluation.get("land_size"))
        legacy_size = parse_float(ai_evaluation.get("size"))
        
        if b_size == 0 and l_size == 0 and legacy_size > 0:
            if selected_type == "condo" or "คอนโด" in selected_type:
                b_size = legacy_size
            else:
                l_size = legacy_size
                
        final_area = b_size if b_size > 0 else l_size
        
        # --- 2. จัดการที่อยู่ ---
        project_name = clean(ai_evaluation.get("project_name"), "-")
        zone_value = raw_data.get("zone") or raw_data.get("Zone") or ""
        address_data = {
            "address": clean(ai_evaluation.get("address"), "-"),
            "city": zone_value if zone_value and zone_value != "-" else clean(ai_evaluation.get("city"), "-"),
            "state": clean(ai_evaluation.get("state"), "-"),
            "sub_district": "-",
            "postal_code": clean(ai_evaluation.get("postal_code"), "-"),
            "country": "Thailand",
            "latitude": str(clean(ai_evaluation.get("latitude"), "0")),
            "longitude": str(clean(ai_evaluation.get("longitude"), "0"))
        }
        
        if project_name != "-":
            from src.services.maps_service import get_location_details
            map_lookup = get_location_details(project_name)
            if map_lookup:
                english_defaults = ["-", "0", "", "Bangkok", "Thailand", "Bangkok City", "Krung Thep Maha Nakhon", None]
                for key in ["address", "city", "state", "sub_district", "postal_code", "country", "latitude", "longitude"]:
                    if address_data.get(key) in english_defaults and map_lookup.get(key):
                        address_data[key] = map_lookup[key]

                base_address = map_lookup.get("address") if map_lookup.get("address") else clean(ai_evaluation.get("address"), "")
                full_addr_parts = [base_address]
                if map_lookup.get("sub_district") and map_lookup.get("sub_district") not in base_address:
                    full_addr_parts.append(f"แขวง/ตำบล {map_lookup['sub_district']}")
                if map_lookup.get("city") and map_lookup.get("city") not in base_address:
                    full_addr_parts.append(f"เขต/อำเภอ {map_lookup['city']}")
                if map_lookup.get("state") and map_lookup.get("state") not in base_address:
                    full_addr_parts.append(f"จังหวัด {map_lookup['state']}")
                combined_address = " ".join([p for p in full_addr_parts if p.strip() and p != "-"])
                address_data["address"] = combined_address if combined_address else "-"
        
        # --- 3. จัดการราคา ห้องนอน ห้องน้ำ location ---
        sell_p_text = clean(ai_evaluation.get("price_sell", "0"), "0")
        rent_p_text = clean(ai_evaluation.get("price_rent", "0"), "0")
        final_sell_price = float(sell_p_text.replace(',', '').split()[0]) if sell_p_text.replace(',', '').replace('.', '', 1).isdigit() else 0
        final_rent_price = float(rent_p_text.replace(',', '').split()[0]) if rent_p_text.replace(',', '').replace('.', '', 1).isdigit() else 0
        
        specs = ai_evaluation.get("specifications", {})
        bedrooms = int(specs.get("bedrooms", 13)) if specs.get("bedrooms") else 13
        bathrooms = int(specs.get("bathrooms", 13)) if specs.get("bathrooms") else 13
        
        # ปรับแก้หา location_val แบบเดียวกับสคริปต์หลัก (sync_to_api.py)
        # เนื่องจากใน DATA_MAPPING ใน config.py ยังไม่มีฟิลด์ locations
        location_val = "109" if "คอนโด" in selected_type or selected_type == "condo" else "131" 
            
        # --- 4. เตรียม Payload (ไม่ส่งรูป) ---
        payload = {
            "owner_is_agent": True,
            "living_level": "normal",
            "customer_name": clean(ai_evaluation.get("customer_name"), "-"),
            "contact_number": clean(ai_evaluation.get("phone_number"), "0"),
            "line_id": clean(ai_evaluation.get("line_id"), ""),
            "area": final_area,
            "building_size": b_size if b_size > 0 else None,
            "land_size": l_size if l_size > 0 else None,
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
            "number": clean(ai_evaluation.get("house_number"), "-"), 
            "city": address_data["city"],
            "state": address_data["state"],
            "district": address_data["city"],
            "province": address_data["state"],
            "subdistrict": address_data["sub_district"] if address_data["sub_district"] != "-" else None,
            "country": address_data["country"],
            "postal_code": address_data["postal_code"],
            "latitude": address_data["latitude"],
            "longitude": address_data["longitude"],
            # เราไม่มีข้อมูลรูปในตอนนี้ เลยตั้งค่าสีคร่าวๆ 
            # ถ้ามีใน specs ก็ส่งไปด้วย จะได้ข้อมูลครบ
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "specifications": specs,
            "specification_values": ai_evaluation.get("specification_values", []),
            "property_initial_owner": clean(ai_evaluation.get("customer_name"), None),
            "property_initial_owner_mobile_number": clean(ai_evaluation.get("phone_number"), None),
        }
        
        # ยิง Update
        if api.update_property(property_id, payload):
            success_count += 1
        else:
            fail_count += 1
            
        time.sleep(2)  # กัน API ฝั่ง Agent โดนยิงรัวเกิน
        
    print(f"\n🎉 สรุปผลการ Update -> สำเร็จ: {success_count} | ล้มเหลว: {fail_count}")

if __name__ == "__main__":
    run_update_batch()
