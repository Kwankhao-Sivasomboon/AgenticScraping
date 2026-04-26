import os
import json
import time
import requests
import re
import urllib.request
import urllib.parse
import datetime as dt_module
from dotenv import load_dotenv

# Use Gemini for translation if needed
try:
    from google import genai
except ImportError:
    genai = None

# Add root folder to sys path to import FirestoreService
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# ==========================================================
# ⚙️ Run Configuration
# ==========================================================
TEST_MODE = True        # 🚩 ตั้งเป็น True เพื่อทดสอบ (ไม่ยิง API จริง)
UPDATE_EXISTING = True    # 🚩 ตั้งเป็น True เพื่ออัปเดตโครงการที่มีอยู่แล้ว (เช่น อัปเดตค่าส่วนกลาง)
COLLECTION = "Leads"    
TARGET_DEVELOPER = "ศุภาลัย" # ปรับตามความต้องการบอสครับ
PROJECT_LIMIT = 5       # 🚩 จำกัดจำนวนโครงการที่จะทำในรอบนี้ (เช่น 5 เพื่อทดสอบ)
API_BASE_URL = os.getenv("AGENT_API_BASE_URL")

# ==========================================================
# 🏢 Known Developer Mapping
# ==========================================================
KNOWN_DEVELOPERS = {
    "เอพี":            {"id": 1,  "name_en": "AP Thai",              "name_th": "เอพี ไทยแลนด์"},
    "แสนสิริ":         {"id": 2,  "name_en": "Sansiri",              "name_th": "แสนสิริ"},
    "เอสซี แอสเสท":   {"id": 3,  "name_en": "SC Asset",             "name_th": "เอสซี แอสเสท"},
    "sc asset":        {"id": 3,  "name_en": "SC Asset",             "name_th": "เอสซี แอสเสท"},
    "อนันดา":          {"id": 4,  "name_en": "Ananda Development",   "name_th": "อนันดา ดีเวลลอปเม้นท์"},
    "แอล.พี.เอ็น":    {"id": 5,  "name_en": "LPN Development",      "name_th": "แอล.พี.เอ็น. ดีเวลลอปเมนท์"},
    "lpn":             {"id": 5,  "name_en": "LPN Development",      "name_th": "แอล.พี.เอ็น. ดีเวลลอปเมนท์"},
    "เมเจอร์":         {"id": 6,  "name_en": "Major Development",    "name_th": "เมเจอร์ ดีเวลลอปเม้นท์"},
    "ณุศาศิริ":        {"id": 7,  "name_en": "Nusasiri",             "name_th": "ณุศาศิริ"},
    "ออริจิ้น":        {"id": 8,  "name_en": "Origin Property",      "name_th": "ออริจิ้น พร็อพเพอร์ตี้"},
    "พฤกษา":          {"id": 9,  "name_en": "Pruksa Real Estate",   "name_th": "พฤกษา เรียลเอสเตท"},
    "ศุภาลัย":         {"id": 10, "name_en": "Supalai",              "name_th": "ศุภาลัย"},
    "แซนด์":           {"id": 11, "name_en": "Sand and Stone",       "name_th": "บริษัท แซนด์ แอนด์ สโตน จำกัด"},
    "สินทัน":          {"id": 12, "name_en": "Sinthai",              "name_th": "สินทัน"},
    "เจซี":            {"id": 13, "name_en": "JC",                   "name_th": "เจซี"},
    "ซีทีซีซี":        {"id": 14, "name_en": "CTCC Engineering",     "name_th": "บริษัท ซีทีซีซี เอ็นจิเนียริ่งจำกัด"},
    "bkk grand":       {"id": 15, "name_en": "BKK Grand Estate",     "name_th": "บีเคเค แกรนด์ เอสเตท"},
}

def match_developer(firestore_dev_name: str):
    name_lower = firestore_dev_name.lower()
    for keyword, dev_info in KNOWN_DEVELOPERS.items():
        if keyword.lower() in name_lower:
            return dev_info
    return None

def is_english(text):
    if not text: return False
    clean_text = re.sub(r'[^a-zA-Zก-๙]', '', str(text))
    if not clean_text: return True
    eng_chars = len(re.findall(r'[a-zA-Z]', clean_text))
    return (eng_chars / len(clean_text)) > 0.5

def translate_name(name, lang="en"):
    if not name: return ""
    has_thai = any('\u0e00' <= char <= '\u0e7f' for char in name)
    try:
        sl, tl = ("th", "en") if lang == "en" else ("en", "th")
        safe_text = urllib.parse.quote(name)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={safe_text}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = urllib.request.urlopen(req, timeout=8)
        data = json.loads(res.read().decode('utf-8'))
        return ''.join([s[0] for s in data[0]]).strip()
    except: return name

def clean_numeric(val, is_price=False):
    if not val: return None
    s_val = str(val).strip().replace(',', '')
    nums = re.findall(r"[-+]?\d*\.\d+|\d+", s_val)
    if not nums: return None
    num_val = float(nums[0])
    if is_price and num_val >= 10000: return round(num_val / 1000000.0, 2)
    return int(num_val)

def convert_to_sqwa(area_str):
    if not area_str: return None
    area_str = str(area_str).replace(",", "").strip()
    match = re.search(r"(\d+)-(\d+)-([\d\.]+)", area_str)
    if match: return (int(match.group(1)) * 400) + (int(match.group(2)) * 100) + float(match.group(3))
    rai = re.search(r"([\d\.]+)\s*ไร่", area_str)
    ngan = re.search(r"([\d\.]+)\s*งาน", area_str)
    wa = re.search(r"([\d\.]+)\s*(?:ตารางวา|วา)", area_str)
    total = 0
    if rai: total += float(rai.group(1)) * 400
    if ngan: total += float(ngan.group(1)) * 100
    if wa: total += float(wa.group(1))
    return float(total) if total > 0 else clean_numeric(area_str)

FACILITY_WHITELIST = {
    "ห้องออกกำลังกาย": "Fitness", "ฟิตเนส": "Fitness", "gym": "Fitness",
    "สระว่ายน้ำ": "Swimming Pool", "swimming pool": "Swimming Pool",
    "สนามหญ้า": "Lawn", "lawn": "Lawn", "สนามเด็กเล่น": "Playground",
    "รปภ": "Security Staff", "security": "Security Staff",
    "กล้องวงจรปิด": "CCTV", "cctv": "CCTV", "garden": "Garden", "สวน": "Garden"
}

def clean_fac(f):
    if not f: return ""
    f_lower = str(f).strip().lower()
    for key, val in FACILITY_WHITELIST.items():
        if key in f_lower: return val
    return ""

def main():
    print(f"🚀 Starting Step 5: Sync Projects (Mode: {'Update' if UPDATE_EXISTING else 'Create Only'})")
    api = APIService()
    if not api.authenticate_staff(): return
    staff_headers = {"Accept": "application/json", "Authorization": f"Bearer {api.staff_token}"}

    fs = FirestoreService()
    docs = fs.db.collection(COLLECTION).get()
    
    project_groups = {}
    for doc in docs:
        data = doc.to_dict()
        p_name = (data.get("project_name") or data.get("sheet_ชื่อโครงการ") or "").strip()
        if not p_name: continue
        dev_name = (data.get("zmyh_developer") or data.get("developer") or "Unknown")
        if p_name not in project_groups: project_groups[p_name] = []
        project_groups[p_name].append({"doc_id": doc.id, **data})

    # Load existing registry
    condo_names = {d.to_dict().get("name_th", ""): d.id for d in fs.db.collection("project_condo").stream()}
    house_names = {d.to_dict().get("name_th", ""): d.id for d in fs.db.collection("project_house").stream()}

    print(f"📊 Total Projects Found: {len(project_groups)}")
    if TARGET_DEVELOPER:
        print(f"🎯 Target Developer: {TARGET_DEVELOPER}")

    processed_count = 0
    for prj_name, leads_list in project_groups.items():
        if PROJECT_LIMIT and processed_count >= PROJECT_LIMIT: break
        
        dev_name_raw = leads_list[0].get("zmyh_developer") or leads_list[0].get("developer") or ""
        dev_info = match_developer(dev_name_raw)
        if not dev_info: continue
        if TARGET_DEVELOPER and TARGET_DEVELOPER not in dev_name_raw: continue

        print(f"\n📌 Project: {prj_name}")
        
        # 1. Handle Language
        prj_th, prj_en = prj_name, ""
        match = re.search(r"^(.*?)\s*\((.*?)\)\s*$", prj_name)
        if match: prj_th, prj_en = match.group(1).strip(), match.group(2).strip()
        else:
            if is_english(prj_name): prj_en = prj_name; prj_th = translate_name(prj_en, "th")
            else: prj_th = prj_name; prj_en = translate_name(prj_th, "en")
        
        if prj_th == prj_en:
            if is_english(prj_en): prj_th = translate_name(prj_en, "th")
            else: prj_en = translate_name(prj_th, "en")

        # 🔥 Update Firestore Names
        for ldoc in leads_list:
            fs.db.collection(COLLECTION).document(ldoc["doc_id"]).update({"name_th": prj_th, "name_en": prj_en})

        # 2. Check if exists
        existing_id = condo_names.get(prj_th) or house_names.get(prj_th)
        is_update = bool(existing_id and UPDATE_EXISTING)
        
        if existing_id and not UPDATE_EXISTING:
            print(f"      ⏭️ Already exists (ID: {existing_id}). Skipping update.")
            continue

        # 3. Aggregate specs
        first = leads_list[0]
        is_house = any(k in str(first.get("property_type", "")).lower() for k in ["บ้าน", "house", "townhome"])
        
        # รวมส่วนกลางจากทุก Lead
        facs_set = {clean_fac(f) for lead in leads_list for f in (lead.get("zmyh_facilities") or []) if clean_fac(f)}
        
        num_units = clean_numeric(next((l.get("zmyh_total_units") for l in leads_list if l.get("zmyh_total_units")), None))
        num_floors = clean_numeric(next((l.get("zmyh_max_floors") for l in leads_list if l.get("zmyh_max_floors")), None))
        num_common_fee = clean_numeric(next((l.get("zmyh_common_fee") for l in leads_list if l.get("zmyh_common_fee")), None))
        num_parking = clean_numeric(next((l.get("zmyh_parking") for l in leads_list if l.get("zmyh_parking")), None))
        num_launch_price = clean_numeric(next((l.get("zmyh_launch_price") for l in leads_list if l.get("zmyh_launch_price")), None), is_price=True)
        num_area = convert_to_sqwa(next((l.get("zmyh_project_area") for l in leads_list if l.get("zmyh_project_area")), None))
        built_year = next((l.get("zmyh_built_year") for l in leads_list if l.get("zmyh_built_year")), None)

        specs = {"facilities": sorted(list(facs_set))}
        if num_units: specs["total_units"] = num_units
        if num_floors: specs["total_floors"] = num_floors
        if num_area: specs["project_area_square_wa"] = num_area
        if num_launch_price: specs["launch_price"] = num_launch_price

        form_data = {
            "developer_id": (None, str(dev_info["id"])),
            "name_en": (None, prj_en), "name_th": (None, prj_th),
            "is_active": (None, "1"),
            "specifications_json": (None, json.dumps(specs))
        }
        if is_update: form_data["_method"] = (None, "PUT") # 👈 บังคับ Laravel ให้เป็น PUT
        if built_year: form_data["built_date"] = (None, f"{built_year}-01-01")
        if num_common_fee: form_data["common_fee"] = (None, str(num_common_fee))
        if num_units: form_data["total_units"] = (None, str(num_units))
        if num_floors: form_data["total_floors"] = (None, str(num_floors))
        if num_area: form_data["project_area_square_wa"] = (None, str(num_area))
        if num_parking: form_data["total_parking_slots"] = (None, str(num_parking))
        if num_launch_price: form_data["launch_price"] = (None, str(num_launch_price))

        project_endpoint = "house-projects" if is_house else "condo-projects"
        api_url = f"{API_BASE_URL}/api/staff/{project_endpoint}"
        if is_update: api_url += f"/{existing_id}"

        try:
            print(f"      🚀 {'UPDATING' if is_update else 'CREATING'} -> {api_url}")
            
            if TEST_MODE:
                print(f"      🧪 [TEST MODE] Skipping API Request. Payload: {prj_th} ({prj_en})")
                processed_count += 1
                continue

            resp = requests.post(api_url, files=form_data, headers=staff_headers, timeout=30)
            if resp.status_code in [200, 201]:
                print(f"      ✅ Success!")
                res_data = resp.json().get("data", {})
                proj_obj = res_data.get("condo_project") or res_data.get("house_project") or res_data
                p_id = proj_obj.get("id") or existing_id
                
                # Save to Registry Firestore
                fs.db.collection("project_house" if is_house else "project_condo").document(str(p_id)).set({
                    "project_id": p_id, "name_th": prj_th, "name_en": prj_en, "synced_at": dt_module.datetime.utcnow().isoformat()
                }, merge=True)
                
                # Link leads
                for ldoc in leads_list:
                    fs.db.collection(COLLECTION).document(ldoc["doc_id"]).update({"project_id": p_id, "project_synced": True})
                processed_count += 1
            else:
                print(f"      ⚠️ Failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e: print(f"      ❌ API Error: {e}")
        time.sleep(1.0)

    print(f"\n🎉 Done! Processed {processed_count} projects.")

if __name__ == "__main__":
    main()
