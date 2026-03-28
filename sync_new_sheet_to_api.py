
import os
import sys
import time
import random
import re
from datetime import datetime

# Setup Root Path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

def clean(val, default="-"):
    if val is None: return default
    s = str(val).strip()
    return s if s and s != "nan" and s != "None" else default

def parse_float(val):
    if val is None: return None
    try:
        s = str(val).replace("฿", "").replace(",", "").strip()
        m = re.search(r'(\d+(\.\d+)?)', s)
        return float(m.group(1)) if m else None
    except: return None

def get_smart(data, search_terms, default="-"):
    for k, v in data.items():
        # แก้บัก: ตัด term ว่างเปล่าออกเพื่อป้องกันการ match ทุก key
        # (ห้ามมี "" ใน search_terms หรือ k จะ match เสมอ)
        if any(term and (term in k) for term in search_terms):
            res = clean(v)
            if res != "-": return res
    return default

def get_price_smart(data, search_terms):
    for k, v in data.items():
        if any(term and (term in k) for term in search_terms):
            val = parse_float(v)
            if val: return val
    return 0

def parse_beds_baths(val, mode="bed"):
    if val is None: return None
    try:
        s = str(val).strip().lower()
        if any(x in s for x in ["studio", "สตูดิโอ", "13", "14"]): return 0
        if mode == "bed":
            m = re.search(r'(\d+)\s*(br|bed|bedroom|นอน)', s)
            if m: return int(m.group(1))
        else:
            m = re.search(r'(\d+)\s*(bt|bath|bathroom|น้ำ)', s)
            if m: return int(m.group(1))
        m = re.search(r'(\d+)', s)
        return int(m.group(1)) if m else None
    except: return None

def parse_floor(val):
    if val is None: return "1"
    s = str(val).strip()
    # พยายามดึงตัวเลขล้วนๆ ออกมา (เช่น "ชั้น 28" -> "28")
    m = re.search(r'(\d+)', s)
    if m: return m.group(1)
    return s if s and s != "-" else "1"

import urllib.request
import urllib.parse
import json

_name_cache = {}

def format_project_name_th_en(name):
    """
    Format and translate project name.
    If mainly Thai -> Translate to EN -> returns 'English Name ( Thai Name )'
    If mainly English -> Translate to TH -> returns 'English Name ( Thai Name )'
    If both exist -> return as is.
    """
    name = str(name).strip()
    if not name or name == "-":
        return name
        
    if name in _name_cache:
        return _name_cache[name]
        
    has_en = bool(re.search(r'[A-Za-z]', name))
    has_th = bool(re.search(r'[\u0E00-\u0E7F]', name))
    
    if has_en and has_th:
        _name_cache[name] = name
        return name
        
    try:
        # มีไทยแต่ไม่มีอังกฤษ -> แปลเป็นอังกฤษ
        if has_th and not has_en:
            safe_text = urllib.parse.quote(name)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=th&tl=en&dt=t&q={safe_text}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, timeout=5)
            data = json.loads(res.read().decode('utf-8'))
            en_name = ''.join([sentence[0] for sentence in data[0]]).title()
            if en_name.lower() != name.lower() and re.search(r'[A-Za-z]', en_name):
                formatted = f"{en_name} ( {name} )"
                _name_cache[name] = formatted
                return formatted
                
        # มีอักฤษแต่ไม่มีไทย -> แปลเป็นไทย
        elif has_en and not has_th:
            safe_text = urllib.parse.quote(name)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q={safe_text}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, timeout=5)
            data = json.loads(res.read().decode('utf-8'))
            th_name = ''.join([sentence[0] for sentence in data[0]])
            if th_name != name and re.search(r'[\u0E00-\u0E7F]', th_name):
                formatted = f"{name} ( {th_name} )"
                _name_cache[name] = formatted
                return formatted
    except Exception as e:
        print(f"      🕵️‍♂️ [Translate Warn] Failed to translate '{name}': {e}")
        pass
        
    _name_cache[name] = name
    return name

def get_dominant_color(room_color, element_color):
    """คำนวณหาสีที่ % รวมสูงสุด (Dominant) และคืนค่าภาษาอังกฤษ (12 Colors Edition)"""
    english_colors = [
        "Green", "Brown", "Red", "Gold", "Orange", "Purple", "Pink", 
        "Yellow", "Gold", "Brown", "White", "Gray", "Blue", "Black"
    ]
    try:
        if not room_color or not element_color: return "-"
        combined = [r + e for r, e in zip(room_color, element_color)]
        max_idx = combined.index(max(combined))
        return english_colors[max_idx]
    except: return "-"

def run_sync_new_sheet(target_arg=None):
    fs = FirestoreService()
    api = APIService()
    mode = "default"
    start_id, end_id, limit_count = None, None, 0
    
    if target_arg:
        arg_lower = str(target_arg).lower()
        if arg_lower == "all": mode = "all"
        elif arg_lower == "nolatlng": mode = "nolatlng"
        elif arg_lower == "unsynced": mode = "unsynced"
        elif arg_lower == "fixlo": mode = "fixlo"
        elif arg_lower == "limit" and len(sys.argv) > 2:
            mode = "limit"
            limit_count = int(sys.argv[2])
        elif arg_lower == "activities":
            mode = "activities"
        elif len(sys.argv) > 2:
            mode = "range"
            start_id, end_id = int(sys.argv[1]), int(sys.argv[2])
        else: mode = "single"

    target_zone = None
    if len(sys.argv) > 3:
        target_zone = sys.argv[3]
    elif len(sys.argv) > 2:
        # 🧠 [Smart Argument Detection] 
        # ถ้าพารามิเตอร์ที่ 2 ไม่ใช่ตัวเลข (ID) และบอสกำลังใช้โหมด all หรือ activities
        # ให้เดาว่าบอสกำลังใส่ "ชื่อโซน" มาให้เลยครับ
        arg2 = sys.argv[2]
        if mode in ["all", "activities"] and not arg2.isdigit():
            target_zone = arg2
            target_arg = "all" # เพื่อให้ FETCH LOGIC ทำงานได้ถูกต้อง
        elif len(sys.argv) > 3:
            target_zone = sys.argv[3]

    print(f"🚀 เริ่มต้นการ Sync ข้อมูล (Mode: {mode}, Target: {target_arg}, Zone Filter: {target_zone or 'None'})...")
    if not api.authenticate(): return

    # --- FETCH LOGIC ---
    if mode == "single":
        query = fs.db.collection(fs.collection_name).where("api_property_id", "in", [int(target_arg), str(target_arg)]).limit(1).get()
        target_items = list(query) if query else [fs.db.collection(fs.collection_name).document(target_arg).get()]
    elif mode == "fixlo":
        print("🛠️ โหมด FixLo: กำลังเตรียมกู้คืนพิกัดสำหรับกลุ่มเป้าหมาย...")
        fix_list = [765,487,1304]
        # ค้นหาทีละตัวจาก Firestore
        target_items = []
        for pid in fix_list:
            docs = list(fs.db.collection(fs.collection_name).where("api_property_id", "in", [int(pid), str(pid)]).limit(1).get())
            if docs: target_items.append(docs[0])
            else: print(f"  ⚠️ ไม่พบ ID {pid} ใน Firestore")
        print(f"🎯 พร้อมซ่อมพิกัดทั้งหมด: {len(target_items)} รายการ")
    elif mode == "unsynced":
        print("🔍 Scanning Firestore specifically for UNSYNCED items (Retry Mode)...")
        # 🎯 กรองเอาตัวที่ยังไม่สำเร็จ และไม่ใช่รายการที่โดน Approve แล้ว
        all_stream = fs.db.collection(fs.collection_name).stream()
        target_items = []
        for d in all_stream:
            data = d.to_dict()
            is_synced = data.get("api_synced", False)
            # 🛡️ เช็คความชัวร์: ต้องยังไม่ซิงค์ และต้องไม่มีธง "Approved" ปักอยู่
            is_approved = data.get("is_approved") or data.get("approved") or (data.get("status") == "approved")
            
            lat = str(data.get("latitude", "0")).strip()
            # 📍 เงื่อนไข 'unsynced' คือมีพิกัดแล้ว (ไม่ใช่ 0) แต่ยังซิงค์ไม่สำเร็จ
            has_latlng = lat and lat not in ["0", "-", "0.0"]

            if not is_synced and not is_approved and has_latlng:
                target_items.append(d)
        print(f"🎯 พบรายการที่ยังซิงค์ไม่จบและพร้อมลุยต่อ: {len(target_items)} รายการ")
    elif mode == "limit":
        print(f"🔬 Searching and Sorting ALL properties for LIMIT {limit_count}...")
        all_docs = list(fs.db.collection(fs.collection_name).stream())
        all_docs.sort(key=lambda x: int(x.to_dict().get("api_property_id") or 999999))
        target_items = all_docs[:limit_count]
        print(f"📊 Total properties in Store: {len(all_docs)} | Processing first {len(target_items)} by ID...")
    elif mode == "nolatlng":
        print("🧭 โหมดพิเศษ: คืนความสว่างให้รายการที่ไร้พิกัด...")
        all_stream = fs.db.collection(fs.collection_name).stream()
        target_items = []
        for d in all_stream:
            data = d.to_dict()
            lat = str(data.get("latitude", "0")).strip()
            lng = str(data.get("longitude", "0")).strip()
            if not lat or not lng or lat in ["0", "-", "0.0"] or lng in ["0", "-", "0.0"]:
                target_items.append(d)
        print(f"🎯 พบรายการที่ขาดพิกัดทั้งหมด: {len(target_items)} รายการ")
    elif mode == "all":
        print(f"🌍 Fetching {'Zone: ' + target_zone if target_zone else 'ALL'} properties from Firestore...")
        if target_zone:
            target_items = list(fs.db.collection(fs.collection_name).where("zone", "==", target_zone).stream())
        else:
            target_items = list(fs.db.collection(fs.collection_name).stream())
        target_items.sort(key=lambda x: int(x.to_dict().get("api_property_id") or 999999))
    elif mode == "range":
        all_stream = fs.db.collection(fs.collection_name).stream()
        target_items = [doc for doc in all_stream if start_id <= int(doc.to_dict().get("api_property_id", 0)) <= end_id]
        target_items.sort(key=lambda x: int(x.to_dict().get("api_property_id") or 999999))
    elif mode == "activities":
        print(f"🎭 โหมด Activities: กำลังกวาดรายการ {'ในโซน ' + target_zone if target_zone else ''} ที่มี ID ทั้งหมดเพื่ออัปเดต Status ใหม่...")
        # ดึงรายการที่มี ID อยู่แล้ว โดยกรองโซนได้ถ้าบอสสั่งมา
        base_query = fs.db.collection(fs.collection_name).where("api_property_id", "!=", None)
        if target_zone:
            base_query = base_query.where("zone", "==", target_zone)
        
        target_items = list(base_query.stream())
        target_items.sort(key=lambda x: int(x.to_dict().get("api_property_id") or 999999))
    else:
        query = fs.db.collection(fs.collection_name).where("is_new_sheet", "==", True).get()
        target_items = list(query)
        target_items.sort(key=lambda x: int(x.to_dict().get("api_property_id") or 999999))

    success_count, fail_count, skipped_count = 0, 0, 0

    for doc in target_items:
        if not doc.exists: continue
        listing_id, raw_data = doc.id, doc.to_dict()
        property_id = raw_data.get("api_property_id")
        
        analysis_doc = fs.db.collection(fs.collection_name).document(listing_id).collection('Analysis_Results').document('evaluation').get()
        ai_evaluation = analysis_doc.to_dict() if analysis_doc.exists else {}

        # 1. Sizes & Type
        b_size = parse_float(raw_data.get("sheet_Area (M)") or raw_data.get("sheet_Area (Sq.m)"))
        l_size = parse_float(raw_data.get("sheet_Area (W)") or raw_data.get("sheet_Area (Sq.w)"))
        raw_type_thai = clean(raw_data.get("sheet_ประเภททรัพย์")).lower()
        if "คอนโด" in raw_type_thai: prop_type = "condo"
        elif any(x in raw_type_thai for x in ["บ้าน", "ทาวน์", "house", "villa"]): prop_type = "house"
        else: prop_type = "condo" if b_size and not l_size else "house"
        final_l_size = 0 if prop_type == "condo" else (l_size or 0)

        # 2. Smart Address & Name
        addr_sheet = get_smart(raw_data, ["Address (API)", "ที่อยู่"])
        addr_raw = clean(raw_data.get("address"))
        addr_ai = clean(ai_evaluation.get("address"))
        p_name = get_smart(raw_data, ["โครงการ", "ชื่อโครงการ"])
        if p_name == "-": p_name = clean(ai_evaluation.get("project_name"))
        
        # 🌐 [NEW] ฟอร์แมตชื่อโปรเจกต์ (แปลไทย-อังกฤษอัตโนมัติ)
        p_name = format_project_name_th_en(p_name)
        
        zone_v = clean(raw_data.get("zone", "-"))
        
        # 🛡️ [ZONE FILTER] ถ้ามีการกำหนดโซนเป้าหมาย ให้ข้ามรายการที่ไม่ตรงออกไป
        if target_zone and zone_v != target_zone:
            # print(f"   ⏭️ Skip {property_id}: Zone '{zone_v}' doesn't match target '{target_zone}'")
            continue
        
        # กรองคำที่ไม่ใช่ชื่อโซนจริงๆ ออกไป
        if zone_v in ["all", "unsynced"]: zone_v = "-"

        # ประกอบ Address หลัก: Sheet > Raw > AI > Project Name
        base_address = addr_sheet if addr_sheet != "-" else (addr_raw if addr_raw != "-" else (addr_ai if addr_ai != "-" else p_name))
        
        # 🌐 [NEW] เติม 'โซน' เข้าไปหน้า Address เพื่อให้ใน agent_api ค้นหาง่ายและสื่อสารชัดเจน
        if zone_v != "-" and zone_v.lower() not in base_address.lower():
            final_address = f"โซน {zone_v} - {base_address}"
        else:
            final_address = base_address

        # 3. Beds/Baths
        ut_raw = get_smart(raw_data, ["Unit Type"])
        beds = parse_beds_baths(ut_raw, "bed") or parse_beds_baths(raw_data.get("sheet_Bed"), "bed") or parse_beds_baths(ai_evaluation.get("bedrooms") or (ai_evaluation.get("specifications") or {}).get("bedrooms"), "bed")
        baths = parse_beds_baths(ut_raw, "bath") or parse_beds_baths(raw_data.get("sheet_Bath"), "bath") or parse_beds_baths(ai_evaluation.get("bathrooms") or (ai_evaluation.get("specifications") or {}).get("bathrooms"), "bath")

        # 4. Pricing & Sale Type
        sor_raw = get_smart(raw_data, ["S or R", "ประเภทการขาย"]).lower()
        sale_type = "sale_or_rent" if any(x in sor_raw for x in ["s/r", "sr", "ขาย/เช่า"]) else ("sale" if any(x in sor_raw for x in ["s", "sell", "sale", "ขาย"]) else ("rent" if any(x in sor_raw for x in ["r", "rent", "เช่า"]) else None))
        sell_p = parse_float(raw_data.get("sheet_ราคาขาย")) or get_price_smart(raw_data, ["ราคาขาย", "Sell", "Price", "Price (Sell)"]) or parse_float(ai_evaluation.get("sell_price") or ai_evaluation.get("price_sell")) or 0
        rent_p = parse_float(raw_data.get("sheet_ราคาเช่า")) or get_price_smart(raw_data, ["ราคาเช่า", "Rent"]) or parse_float(ai_evaluation.get("rental_price") or ai_evaluation.get("rent_price")) or 0
        if not sale_type: sale_type = "sale_or_rent" if (sell_p and rent_p) else ("rent" if rent_p else "sale")

        # 5. House Color & Floor
        h_color = get_dominant_color(raw_data.get("room_color") or ai_evaluation.get("room_color"), raw_data.get("element_color") or ai_evaluation.get("element_color"))
        floor_raw = get_smart(raw_data, ["ชั้น", "Floor"])
        floor_v = parse_floor(floor_raw) # [FIXED] ใช้ parse_floor กรองให้เหลือแค่ตัวเลข
        if floor_v == "1" and ai_evaluation.get("floor"):
             floor_v = parse_floor(ai_evaluation.get("floor"))

        # 6. Payload
        # [NEW] จัดการ City (เขต/อำเภอ) ให้ตรงตามโซนใน Sheet
        # ถ้าไม่มีโซนใน Sheet (หรือเป็น all/-) ให้ใช้ City จาก Google Maps (Fallback)
        final_city = zone_v if zone_v != "-" else ""
        
        payload = {
            "property_initial_owner": clean(raw_data.get("sheet_ชื่อเจ้าของ") or ai_evaluation.get("owner_name"), "-"),
            "property_initial_owner_mobile_number": clean(raw_data.get("sheet_เบอร์โทรเจ้าของ") or ai_evaluation.get("extracted_phone"), "0"),
            "building_size": b_size or 0, "land_size": final_l_size, "built": datetime.now().strftime("%Y-%m-%d"),
            "name": p_name, "type": prop_type, "sale_type": sale_type, "status": "available", "price": sell_p, "monthly_rental_price": rent_p,
            "address": final_address, "latitude": parse_float(raw_data.get("latitude") or ai_evaluation.get("latitude")), "longitude": parse_float(raw_data.get("longitude") or ai_evaluation.get("longitude")),
            "city": final_city, # 🏙️ เพิ่มฟีลด์ City (เขต/อำเภอ) ลงไปในพุง Payload
            "house_color": h_color, "bedrooms": beds or 0, "bathrooms": baths or 0,
            "garage": parse_float(ai_evaluation.get("parking_count") or (ai_evaluation.get("specifications") or {}).get("parking_spaces")) or 0
        }
        
        # 7. Specs
        style_v = clean(raw_data.get("architect_style") or raw_data.get("interior_style") or ai_evaluation.get("interior_style"))
        payload["specifications"] = {
            "floor": str(floor_v),      # ส่งทั้งแบบเอกพจน์
            "floors": str(floor_v),     # และพหูพจน์ เพื่อความชัวร์
            "bedrooms": str(beds or 0),
            "bathrooms": str(baths or 0),
            "parking_spaces": str(int(payload["garage"])),
            "style": style_v if style_v != "-" else "Other",
            "interior_style": style_v if style_v != "-" else "Other", # ส่ง interior_style ควบไปด้วย
            "architect_style": style_v if style_v != "-" else "Other" # ส่ง architect_style ควบไปด้วย
        }
        payload["specification_values"] = {"common_facilities": ai_evaluation.get("common_facilities", ["-"])}

        # 🎯 [โหมด FixLo] บังคับล้างพิกัดทิ้งเพื่อให้เข้าสู่ลอจิกการหาใหม่ด้านล่าง
        if mode == "fixlo":
            print(f"🔄 ID {property_id}: บังคับค้นหาพิกัดใหม่ทับของเก่าที่เพี้ยน...")
            payload["latitude"], payload["longitude"] = None, None

        if not payload["latitude"] or not payload["longitude"] or payload["latitude"] == "0" or payload["longitude"] == "0":
            print(f"🕵️‍♂️ Missing Lat/Lng for '{payload['name']}'. Attempting Google Maps Lookup...")
            from src.services.maps_service import get_location_details
            
            # ลองใช้ชื่อโครงการ หรือ ที่อยู่ หาพิกัด
            search_query = payload["name"] if payload["name"] != "-" else payload["address"]
            map_info = get_location_details(search_query)
            
            if map_info and map_info.get("latitude"):
                payload["latitude"] = map_info["latitude"]
                payload["longitude"] = map_info["longitude"]
                
                if payload["address"] == "-": 
                    payload["address"] = map_info["address"]
                
                # 🏙️ [FALLBACK] ถ้า City ยังว่างอยู่จนถึงตอนนี้ ให้ดึงข้อมูลที่ใกล้เคียงที่สุดจาก Google มาใส่ (ห้ามส่งค่าว่าง!)
                if not payload.get("city"):
                    payload["city"] = map_info.get("city") or map_info.get("state") or map_info.get("sub_district") or map_info.get("postal_code") or "-"
                    print(f"   🏙️ Found Fallback City: {payload['city']}")
                
                # 🛠️ [SAVE BACK] บันทึกพิกัดและที่อยู่ใหม่กลับลง Firestore ทันที
                save_data = {
                    "latitude": payload["latitude"],
                    "longitude": payload["longitude"],
                    "address": payload["address"],
                    "city": payload["city"]
                }
                fs.db.collection(fs.collection_name).document(listing_id).update(save_data)
                print(f"   ✅ Foundry: {payload['latitude']}, {payload['longitude']} (Saved All to Firestore)")
                
                # --- [NEW] พักหายใจ 1 วิ ก่อนจะไปลุยยิง API ต่อยอด ---
                time.sleep(1.0)
            else:
                print(f"⚠️ Skip {listing_id}: No Lat/Lng found even after Maps lookup")
                skipped_count += 1
                continue

        api_success = False
        if property_id:
            # 🕵️‍♂️ [API Direct Check] เช็คสถานะจริงจาก API แบบเรียลไทม์ (ตามที่บอสสั่ง)
            print(f"🔍 Checking Status for {property_id} on API...")
            p_status_info = api.get_property_status(property_id)
            
            # 🛡️ แปรรูปสถานะให้เป็นตัวเลือกที่ชัดเจน (รองรับค่าว่างหรือ None)
            app_status = str(p_status_info or "").strip().lower()
            print(f"   📥 API Status Result: '{app_status}' (from /status endpoint)")
            
            if "approve" in app_status:
                print(f"   ⏭️ Skip {property_id}: Already Approved on API (Confirmed by GET /status)")
                skipped_count += 1
                # อัปเดตสถานะใน Firestore ให้ตรงกันด้วย จะได้ไม่หลุดมาในลูปหน้า
                fs.db.collection(fs.collection_name).document(listing_id).update({
                    "is_new_sheet": False,
                    "api_synced": True,
                    "is_approved": True
                })
                continue
            
            # [NEW] ถ้าเป็นโหมด activities ให้ข้ามการอัปเดตข้อมูลทรัพย์ไปเลย
            if mode == "activities":
                print(f"   ⚡ Mode Activities: Skipping property update, proceeding to Activity Log...")
                api_success = True 
            else:
                api_success = api.update_property(property_id, payload)
        else:
            # รายการใหม่ยังไงก็ต้องสร้างก่อนถึงจะยิง Activity ได้
            new_id = api.create_property(payload)
            if new_id: 
                property_id = new_id
                fs.db.collection(fs.collection_name).document(listing_id).update({"api_property_id": property_id})
                api_success = True

        if api_success:
            if mode == "activities":
                print(f"✅ Activity Sync {property_id} Success (Processing Logs...)")
            else:
                print(f"✅ Sync {property_id} Success (Color: {h_color}, Floor: {floor_v})")
            
            success_count += 1
            
            # 📋 [NEW] ACTIVITY LOGGING WORKFLOW
            # ดึงข้อมูลกิจกรรมจาก Sheet
            sheet_call_status = clean(raw_data.get("sheet_สถานะการโทร"), "").strip()
            sheet_remark = clean(raw_data.get("sheet_Remark"), "").strip()
            sheet_feedback = clean(raw_data.get("sheet_Feedback"), "").strip()
            sheet_call_date = clean(raw_data.get("sheet_วันที่โทร"), "").strip()
            
            # รวม Remark และ Feedback เข้าด้วยกัน
            combined_notes = f"{sheet_remark} {sheet_feedback}".strip() or "-"
            
            if sheet_call_status:
                activity_payload = {}
                status_lower = sheet_call_status.lower()
                
                # ตัดสินใจประเภท Activity
                if any(x in status_lower for x in ["ตกลง", "ยอมรับ", "accept"]):
                    activity_payload = {
                        "type": "accept",
                        "reason": combined_notes,
                        "notes": "บันทึกอัตโนมัติจาก Sheet"
                    }
                elif any(x in status_lower for x in ["ปฏิเสธ", "ไม่สนใจ", "deny", "ไม่รับ"]):
                    activity_payload = {
                        "type": "deny",
                        "reason": combined_notes,
                        "notes": "บันทึกอัตโนมัติจาก Sheet"
                    }
                else:
                    # กรณีเป็น Call Log ปกติ
                    # แมพค่า call_outcome ให้ตรงกับที่ API คาดหวัง (reached, no_answer, etc.)
                    outcome = "reached"
                    if any(x in status_lower for x in ["ไม่รับ", "ฝากข้อความ", "no answer"]): outcome = "no_answer"
                    elif "โทรใหม่" in status_lower: outcome = "callback_later"
                    elif "เบอร์ผิด" in status_lower: outcome = "wrong_number"
                    
                    activity_payload = {
                        "type": "call",
                        "call_outcome": outcome,
                        "notes": f"[{sheet_call_status}] {combined_notes}"
                    }
                
                # ถ้ามีวันที่ระบุใน Sheet ให้ใส่ไปด้วย
                if sheet_call_date and sheet_call_date != "-":
                    activity_payload["occurred_at"] = sheet_call_date
                
                # ยิง Activity เข้า API
                api.create_activity(property_id, activity_payload)
            
            # --- [NEW] 1. บันทึก 'color' กลับไปใน Leads (เฉพาะ Color เพื่อความคลีน)
            # --- [NEW] 1. บันทึกสถานะกลับไปใน Leads
            update_fields = {
                "is_new_sheet": False, 
                "api_synced": True
            }
            # 🎨 ถ้าไม่ใช่โหมด activities ให้บันทึกสีลง Firestore ด้วย
            if mode != "activities":
                update_fields["color"] = h_color
                
            fs.db.collection(fs.collection_name).document(listing_id).update(update_fields)
            
            # --- [NEW] 2. เก็บ Cache ข้อมูลเข้าตะกร้าใหม่ใน Firestore (ไม่ปนกับ Leads)
            # สร้าง Collection ชื่อ 'API_Cache' เพื่อเก็บ Log & Payload ชุดเต็ม
            cache_payload = dict(payload)
            cache_payload["synced_at"] = datetime.now()
            cache_payload["listing_id"] = listing_id
            
            fs.db.collection("API_Cache").document(str(property_id)).set(cache_payload, merge=True)
            
            # --- [NEW] 3. (แถม) เก็บลง Local Folder เหมือนเดิมเพื่อความชัวร์
            import json
            cache_dir = os.path.join(project_root, "api_cache")
            os.makedirs(cache_dir, exist_ok=True)
            cache_path = os.path.join(cache_dir, f"{property_id}_{listing_id}.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                
        else: 
            p_desc = f"Property {property_id}" if property_id else f"Listing {listing_id}"
            print(f"❌ {p_desc} FAILED during API Sync. Check response logs above.")
            fail_count += 1
        
        # --- พักเครื่อง 3-5 วินาที เพื่อความเนียนและมั่นคง (บอสสั่งมา!) ---
        time.sleep(random.uniform(3.0, 5.0))

    print(f"\n🎉 สรุปผล: สำเร็จ {success_count} | ข้าม {skipped_count} | ล้มเหลว {fail_count}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    run_sync_new_sheet(target)
