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
TEST_MODE = False       # ปรับเป็น False เมื่อพร้อมยิง API จริง

# กำหนดชื่อ Developer ที่ต้องการ Process (ใส่ keyword จาก KNOWN_DEVELOPERS ด้านล่าง)
TARGET_DEVELOPER = "แสนสิริ"

# จำนวนโครงการสูงสุดที่จะ Process ต่อ 1 รัน (None = ไม่จำกัด)
PROJECT_LIMIT = None

# ดึง URL จาก AGENT_API_BASE_URL ที่บอสมีใน .env
API_BASE_URL = os.getenv("AGENT_API_BASE_URL")

# ==========================================================
# 🏢 Known Developer Mapping (Firestore name -> System ID)
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

try:
    from unidecode import unidecode
except ImportError:
    unidecode = None

_translate_cache = {}

def translate_name(name, lang="en"):
    """แปลชื่อโครงการโดยใช้ Google Translate HTTP API (ไม่ต้องพึ่ง library)"""
    if not name: return ""
    if name in _translate_cache: return _translate_cache[name]
    
    has_thai = bool(re.search(r'[\u0E00-\u0E7F]', name))
    
    translated = name
    try:
        if lang == "en" and has_thai:
            safe_text = urllib.parse.quote(name)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=th&tl=en&dt=t&q={safe_text}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, timeout=8)
            data = json.loads(res.read().decode('utf-8'))
            translated = ''.join([s[0] for s in data[0]]).strip()
    except Exception as e:
        print(f"      ⚠️ Google Translate Error: {e}")
        if unidecode and has_thai:
            translated = unidecode(name)

    # 2. ใช้ Gemini ช่วยจูน Branding ให้ดูสวย (ถ้ามี API Key)
    api_key = os.getenv("GEMINI_API_KEY")
    if genai and api_key and translated:
        try:
            client = genai.Client(api_key=api_key)
            prompt = (
                f"Fix this property name to look professional for a website.\n"
                f"Original Thai: '{name}'\n"
                f"English Draft: '{translated}'\n"
                f"Rules:\n"
                f"1. Use official branding like 'd condo' for 'ดี คอนโด'.\n"
                f"2. Return ONLY the polished English name, NO THAI."
            )
            resp = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
            polished = resp.text.strip().replace('"', '').replace("'", "")
            if polished and not any(u'\u0e00' <= c <= u'\u0e7f' for c in polished):
                translated = polished
        except: pass
    
    # 3. ด่านสุดท้าย: ล้างภาษาไทยทิ้งแบบ 100% (ใช้การแปลงเสียงอ่านแทนการตัดทิ้ง)
    if any(u'\u0e00' <= c <= u'\u0e7f' for c in translated):
        if unidecode:
            translated = unidecode(translated)
        # ถ้ายังค้างสิ่งที่ไม่ใช่ตัวพิมพ์มาตรฐาน ให้ลบเฉพาะสัญลักษณ์แปลกๆ ไม่ใช่ตัวอักษร
        translated = re.sub(r'[^\x20-\x7e]+', '', translated).strip()
            
    return translated if translated else name

def is_english(text):
    if not text: return False
    # นับเฉพาะตัวอักษรภาษาอังกฤษเทียบกับความยาวทั้งหมด (ตัดเลขและสัญลักษณ์)
    letters = re.sub(r'[^A-Za-z]', '', str(text))
    if not letters: return False
    # ถ้ามีตัวอักษรภาษาอังกฤษมากกว่า 60% ของตัวอักษรทั้งหมด ถือว่าเป็นภาษาอังกฤษ
    all_alphas = re.sub(r'[^\u0E00-\u0E7FA-Za-z]', '', str(text))
    if not all_alphas: return False
    return len(letters) / len(all_alphas) > 0.6

def safe_float(val):
    try: return float(val)
    except: return None

def main():
    print("🚀 Starting Step 5: Sync API Project Creation")
    
    # 🔐 บังคับดึง Token ใหม่จาก Staff Login อัตโนมัติ
    api = APIService()
    if not api.authenticate_staff():
        print("❌ Staff Authentication Failed. Please check STAFF_API_EMAIL/PASSWORD in .env")
        return
        
    STAFF_TOKEN = api.staff_token  # ✅ ต้องใช้ staff_token ไม่ใช่ token (agent)
    print(f"✅ Staff Auth Success. Target: {API_BASE_URL}")
    print(f"   🔑 Token preview: {STAFF_TOKEN[:20] if STAFF_TOKEN else 'EMPTY'}...")

    staff_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {STAFF_TOKEN}"
    }

    # ========================================================
    # 🔍 ดึง Developer List จาก API จริง (ไม่ Hardcode)
    # ========================================================
    print("\n🔍 Fetching Developer list from API...")
    api_developers = {}  # slug/keyword -> {id, name_en, name_th}
    try:
        dev_resp = requests.get(
            f"{API_BASE_URL}/api/public/developers",
            headers={"Accept": "application/json"},
            timeout=15
        )
        if dev_resp.status_code == 200:
            dev_data = dev_resp.json()
            dev_list = dev_data.get("data", dev_data) if isinstance(dev_data, dict) else dev_data
            if isinstance(dev_list, dict): dev_list = dev_list.get("data", [])
            for d in dev_list:
                dev_id   = d.get("id")
                name_en  = d.get("name_en", "")
                name_th  = d.get("name_th", "")
                slug     = d.get("slug", "")
                # เก็บ key หลายแบบเพื่อให้ Match ชื่อ Firestore ได้ง่าย
                for key in [name_en.lower(), name_th, slug]:
                    if key:
                        api_developers[key] = {"id": dev_id, "name_en": name_en, "name_th": name_th}
            print(f"✅ Loaded {len(dev_list)} developers from API")
            for d in dev_list:
                print(f"   ID {d.get('id'):>3} | {d.get('name_en')} / {d.get('name_th')}")
        else:
            print(f"⚠️ Could not load developers from API ({dev_resp.status_code}). Falling back to KNOWN_DEVELOPERS map.")
    except Exception as e:
        print(f"⚠️ Developer API Error: {e}. Falling back to KNOWN_DEVELOPERS map.")

    def resolve_developer_id(firestore_dev_name: str):
        """Match ชื่อจาก Firestore กับ Developer ใน API โดย keyword matching"""
        name_lower = firestore_dev_name.lower()
        # ลอง match กับ key ใน api_developers ก่อน
        for key, info in api_developers.items():
            if key and (key in name_lower or name_lower in key):
                return info
        # fallback ไปที่ KNOWN_DEVELOPERS เดิม
        return match_developer(firestore_dev_name)

    fs = FirestoreService()
    if not fs.db:
        print("❌ Cannot connect to Firestore.")
        return
        
    print("⏳ Fetching leads...")
    docs = fs.db.collection("Leads").get()
    
    developer_groups = {}
    for doc in docs:
        doc_id = doc.id
        data = doc.to_dict()
        dev_name = data.get("zmyh_developer", "").strip() or "Unknown Developer"
        prj_name = data.get("sheet_ชื่อโครงการ", "").strip()
        if not prj_name: continue
        
        if dev_name not in developer_groups:
            developer_groups[dev_name] = {}
        if prj_name not in developer_groups[dev_name]:
            developer_groups[dev_name][prj_name] = []
        # เก็บทั้ง doc_id ไว้ด้วยเพื่อ update ภายหลัง
        developer_groups[dev_name][prj_name].append({"doc_id": doc_id, **data})
        
    if TEST_MODE:
        print("\n--- 🧪 TEST MODE: Generating HTML Facilities Report ---")
        total_projects = 0
        all_unique_facilities = set()
        report_data = [] # List of {dev: name, projects: [{name: n, facs: []}], unique_facs: []}

        for dev_name, projects in developer_groups.items():
            dev_facilities = set()
            dev_projects_list = []
            
            def clean_fac(f):
                if not f: return ""
                f = f.strip().lower()
                f = re.sub(r"\(.*?\)", "", f).strip()
                
                # 🧠 [Mega Semantic Mapping] กวาดล้างครั้งใหญ่
                # ลำดับมีความสำคัญ: เอาคำเฉพาะขึ้นก่อนคำกว้าง
                mapping = {
                    # --- Thai Standard ---
                    "ห้องออกกำลังกาย": "fitness", "สระว่ายน้ำ": "swimming pool", "สระว่ายนํ้า": "swimming pool",
                    "ลิฟท์": "elevator", "ลิฟต์": "elevator", "สวนหย่อม": "garden", "สวนส่วนกลาง": "garden",
                    "ที่จอดรถ": "parking", "ลานจอดรถ": "parking", "กล้องวงจรปิด": "cctv",
                    "ระบบความปลอดภัย": "security 24hr", "รปภ": "security 24hr", "รักษาความปลอดภัย": "security 24hr",
                    "โถงต้อนรับ": "lobby", "ห้องสมุด": "library", "ห้องอเนกประสงค์": "multipurpose room",
                    "อเนกประสงค์": "multipurpose room", "เอนกประสงค์": "multipurpose room",
                    "สนามเด็กเล่น": "playground", "คีย์การ์ด": "keycard access", "ประตูทางเข้า-ออกโครงการ": "gate access",
                    
                    # --- Search & Grouping Rules ---
                    "bbq": "bbq area", "บาร์บีคิว": "bbq area",
                    "shuttle": "shuttle service", "รับ-ส่ง": "shuttle service", "รับส่ง": "shuttle service",
                    "fitness": "fitness", "gym": "fitness", "ยิม": "fitness", "exercise": "fitness", "spinning": "fitness", "cardio": "fitness",
                    "pool": "swimming pool", "swimming": "swimming pool", "jacuzzi": "jacuzzi", "จากุซซี่": "jacuzzi",
                    "sauna": "sauna", "ซาวน่า": "sauna", "steam": "steam room", "สตรีม": "steam room", "onsen": "onsen",
                    "garden": "garden", "park": "garden", "green": "garden", "พื้นที่สีเขียว": "garden", "pavilion": "pavilion", "ศาลา": "pavilion",
                    "co-working": "co-working space", "working": "co-working space", "co-living": "co-living space",
                    "meeting": "meeting room", "ประชุม": "meeting room", "lounge": "lounge", "เลานจ์": "lounge",
                    "theater": "mini theater", "theatre": "mini theater", "cinema": "mini theater", "หนัง": "mini theater", "โรงภาพยนตร์": "mini theater",
                    "playground": "playground", "kid": "playground", "เด็ก": "playground", "playroom": "playground",
                    "keycard": "keycard access", "key card": "keycard access", "access card": "keycard access", "door lock": "keycard access", "doorlock": "keycard access", "สแกน": "biometric access",
                    "security": "security 24hr", "cctv": "cctv", "กล้องวงจร": "cctv",
                    "parking": "parking", "automatic parking": "auto parking",
                    "lobby": "lobby", "waiting": "lobby", "reception": "lobby",
                    "jogging": "jogging track", "walking track": "jogging track", "วิ่ง": "jogging track",
                    "library": "library", "study": "library", "reading": "library",
                    "ev charger": "ev charger", "ชาร์จรถ": "ev charger",
                    "sky": "sky facilities", "roof": "sky facilities", "ดาดฟ้า": "sky facilities", "horizon": "sky facilities",
                    "golf": "golf simulator", "กอล์ฟ": "golf simulator",
                    "game": "game room", "gaming": "game room", "เกม": "game room",
                    "yoga": "yoga room", "โยคะ": "yoga room",
                    "spa": "spa room", "massage": "spa room", "นวด": "spa room", "salon": "salon",
                    "mail": "mail room", "จดหมาย": "mail room",
                    "laundry": "laundry room", "ซัก": "laundry room", "washer": "laundry room",
                    
                    # --- Luxury / Specific Names (Grouping to Standard) ---
                    "atrium": "lobby", "clover": "garden", "forest": "garden", "botany": "garden",
                    "social club": "clubhouse", "residential club": "clubhouse", "lifestyle club": "clubhouse",
                    "cabin": "pavilion", "retreat": "pavilion", "pavilion": "pavilion",
                    "observatorium": "sky facilities", "observatory": "sky facilities",
                    "celebrity": "lounge", "executive": "lounge", "passion": "lounge",
                    "mini bar": "lounge", "wine bar": "lounge", "wine cellar": "lounge",
                    "station": "co-working space", "creative studio": "co-working space", "live studio": "co-working space",
                    "retail": "shops", "shop": "shops", "minimart": "shops", "maxvalu": "shops", "convenience store": "shops", "starbucks": "shops",
                    "cafe": "shops", "coffee": "shops", "restaurant": "shops", "อาหาร": "shops", "เสริมสวย": "shops",
                    "shuttle": "shuttle service", "รับส่ง": "shuttle service", "รับ-ส่ง": "shuttle service", "car sharing": "shuttle service",
                    "vending": "vending machine", "ตู้หยอดเหรียญ": "vending machine",
                    "wifi": "wi-fi", "wi-fi": "wi-fi", "internet": "wi-fi", "อินเตอร์เน็ต": "wi-fi",
                    "สวน": "garden", "garden": "garden", "park": "garden", "green": "garden", "trees": "garden", "หย่อม": "garden",
                    "boxing": "boxing area", "ชกมวย": "boxing area", "มวย": "boxing area",
                    "pet": "pet area", "สัตว์เลี้ยง": "pet area",
                    "bicycle": "bicycle track", "จักรยาน": "bicycle track", "bike": "bicycle track",
                    "katsan": "gate access", "easy pass": "gate access", "ทางเข้า": "gate access", "รั้ว": "gate access", "ประตู": "gate access",
                    " multipurpose": "multipurpose room", "อเนกประสงค์": "multipurpose room", "เอนกประสงค์": "multipurpose room", "กิจกรรม": "multipurpose room", "เปี่ยมสุข": "multipurpose room", "housework": "multipurpose room",
                    "laundry": "laundry room", "ซัก": "laundry room", "washer": "laundry room", "washing": "laundry room"
                }
                
                # 🚫 Exclude List: สิ่งที่ไม่ใช่ Facilities จริงๆ
                excludes = [
                    "ริมแม่น้ำ", "ติดแม่น้ำ", "chaophraya", "ริมน้ำ", "แม่น้ำ", "เจ้าพระยา",
                    "ถนนกว้าง", "รั้วสูง", "12 ม.", "9 ม.", "2.5 เมตร", "สายไฟฟ้าใต้ดิน",
                    "1 ปี", "350 เมตร", "bts", "mrt", "ใกล้", "ติด", "ห่างจาก",
                    "ระบบป้องกันอัคคีภัย", "smoke", "detector", "heat", "fire alarm",
                    "ระบบสัญญาณกันขโมย", "magnetic", "motion sensor", "tv", "สายอากาศ", "เคเบิ้ล"
                ]
                
                for ex in excludes:
                    if ex in f: return ""

                for key, val in mapping.items():
                    if key in f: return val
                
                return f

            for prj_name, leads_list in projects.items():
                prj_facilities = set()
                for lead in leads_list:
                    facs = lead.get("zmyh_facilities")
                    if isinstance(facs, list):
                        for f in facs: 
                            cleaned = clean_fac(f)
                            if cleaned: prj_facilities.add(cleaned)
                    elif isinstance(facs, str) and facs:
                        for f in facs.split(","):
                            cleaned = clean_fac(f)
                            if cleaned: prj_facilities.add(cleaned)
                
                dev_projects_list.append({
                    "name": prj_name,
                    "lead_count": len(leads_list),
                    "facilities": sorted(list(prj_facilities))
                })
                dev_facilities.update(prj_facilities)
            
            report_data.append({
                "developer": dev_name,
                "projects": dev_projects_list,
                "unique_facilities": sorted(list(dev_facilities))
            })
            all_unique_facilities.update(dev_facilities)
            total_projects += len(projects)

        # --- Generate HTML ---
        css_style = """
            :root {
                --primary: #2563eb;
                --dark: #1e293b;
                --light: #f8fafc;
                --accent: #f59e0b;
            }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: var(--light); color: var(--dark); margin: 0; padding: 20px; }
            .container { max-width: 1200px; margin: auto; }
            header { background: var(--dark); color: white; padding: 30px; border-radius: 15px; margin-bottom: 30px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); }
            h1 { margin: 0; font-size: 24px; }
            .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-top: 20px; }
            .stat-card { background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px; text-align: center; }
            .stat-value { font-size: 28px; font-weight: bold; color: var(--accent); }
            
            .dev-section { background: white; border-radius: 15px; padding: 25px; margin-bottom: 30px; box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1); }
            .dev-header { border-bottom: 2px solid #e2e8f0; padding-bottom: 15px; margin-bottom: 20px; display: flex; align-items: baseline; gap: 15px; }
            .dev-title { color: var(--primary); font-size: 20px; font-weight: bold; }
            
            .project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
            .project-card { border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; background: #fff; }
            .project-name { font-weight: bold; margin-bottom: 10px; color: #475569; }
            
            .tag-container { display: flex; flex-wrap: wrap; gap: 5px; }
            .tag { background: #eff6ff; color: #1e40af; padding: 4px 10px; border-radius: 20px; font-size: 11px; border: 1px solid #bfdbfe; }
            .tag-all { background: #fef3c7; color: #92400e; border-color: #fde68a; font-weight: bold; }
            
            .footer { text-align: center; margin-top: 50px; color: #64748b; font-size: 14px; }
        """
        
        global_tags = "".join([f'<span class="tag tag-all">{f}</span>' for f in sorted(list(all_unique_facilities))])
        
        dev_sections = []
        for d in report_data:
            project_cards = []
            for p in d['projects']:
                tags = "".join([f'<span class="tag">{tf}</span>' for tf in p['facilities']]) or '<span style="color:#cbd5e1; font-size:12px;">No facilities data</span>'
                card = f"""
                <div class="project-card">
                    <div class="project-name">📌 {p['name']} <small style="color:#94a3b8; font-weight:normal">({p['lead_count']} leads)</small></div>
                    <div class="tag-container">{tags}</div>
                </div>
                """
                project_cards.append(card)
            
            section = f"""
            <div class="dev-section">
                <div class="dev-header">
                    <span class="dev-title">{d['developer']}</span>
                    <span style="color: #64748b; font-size: 0.9em;">({len(d['projects'])} Projects)</span>
                </div>
                <div class="project-grid">
                    {" ".join(project_cards)}
                </div>
            </div>
            """
            dev_sections.append(section)

        now_str = dt_module.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        html_content = f"""
        <!DOCTYPE html>
        <html lang="th">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Facilities Report - Step 5</title>
            <style>{css_style}</style>
        </head>
        <body>
            <div class="container">
                <header>
                    <h1>🏢 Property Facilities Dashboard</h1>
                    <div class="stats-grid">
                        <div class="stat-card"><div class="stat-value">{len(developer_groups)}</div><div>Developers</div></div>
                        <div class="stat-card"><div class="stat-value">{total_projects}</div><div>Projects</div></div>
                        <div class="stat-card"><div class="stat-value">{len(all_unique_facilities)}</div><div>Unique Facilities</div></div>
                    </div>
                </header>

                <div class="dev-section">
                    <h2 style="color: var(--dark)">🌐 Global Facilities Summary</h2>
                    <div class="tag-container">{global_tags}</div>
                </div>

                {" ".join(dev_sections)}

                <div class="footer">
                    Generated at {now_str} | PainpointToday Agentic Scraping
                </div>
            </div>
        </body>
        </html>
        """
        
        report_path = "step5_facilities_report.html"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print(f"\n✅ HTML Report Generated at: {os.path.abspath(report_path)}")
        print(f"👉 เปิดไฟล์เพื่อดูสรุปสสวยๆ ได้เลยครับ!")
        return

    # --- โหลดชื่อโครงการที่สร้างแล้วจาก project_condo และ project_house ---
    print("\n📂 Loading existing projects from Firestore...")
    condo_names = {d.to_dict().get("name_th", "") for d in fs.db.collection("project_condo").stream()}
    house_names = {d.to_dict().get("name_th", "") for d in fs.db.collection("project_house").stream()}
    print(f"   📦 Existing Condos: {len(condo_names)} | Houses: {len(house_names)}")

    # --- Real Processing ---
    project_count = 0
    
    for dev_name, projects in developer_groups.items():
        dev_info = resolve_developer_id(dev_name)
        if not dev_info: continue
        if TARGET_DEVELOPER and TARGET_DEVELOPER.lower() not in dev_name.lower(): continue
            
        developer_id = dev_info["id"]
        print(f"\n🏢 Found Developer: {dev_name} → ID: {developer_id} ({dev_info['name_en']} / {dev_info['name_th']})")
        
        for prj_name, leads_list in projects.items():
            if PROJECT_LIMIT and project_count >= PROJECT_LIMIT: break

            print(f"   📌 Project: {prj_name}")
            prj_name_th = prj_name
            prj_name_en = ""
            
            # 🔍 เช็คแบบ "ชื่อไทย (English Name)"
            match_paren = re.search(r"^(.*?)\s*\((.*?)\)\s*$", prj_name)
            if match_paren:
                prj_name_th = match_paren.group(1).strip()
                prj_name_en = match_paren.group(2).strip()
                print(f"      📦 Parentheses Split -> TH: '{prj_name_th}', EN: '{prj_name_en}'")
            
            # 🔍 เช็คซ้ำจากโครงการที่โหลดมาตอนเริ่มรัน
            if prj_name_th in condo_names or prj_name_th in house_names:
                print(f"      ⏭️  Skipped (มีอยู่ใน Firestore Registry แล้ว)")
                continue
                
            # 🤖 ถ้ายังไม่มีชื่ออังกฤษ หรือชื่ออังกฤษเป็นไทย ให้ใช้ AI/Google แปล
            if not prj_name_en or not is_english(prj_name_en):
                prj_name_en = translate_name(prj_name_th, "en")
            
            # เช็คซ้ำด้วยชื่ออังกฤษอีกรอบ (เผื่อชื่อไทยไม่ตรงแต่ชื่ออังกฤษตรง)
            if prj_name_en in condo_names or prj_name_en in house_names:
                print(f"      ⏭️  Skipped (ชื่ออังกฤษ '{prj_name_en}' ซ้ำใน Registry)")
                continue
            
            first_lead = leads_list[0]
            prop_type_raw = str(first_lead.get("property_type", "") or first_lead.get("sheet_ประเภททรัพย์", "")).lower()
            is_house = any(k in prop_type_raw for k in ["บ้าน", "house", "townhome"])
            project_endpoint = "house-projects" if is_house else "condo-projects"
            project_type = "house" if is_house else "condo"
            collection_name = "project_house" if is_house else "project_condo"
            name_registry = house_names if is_house else condo_names

            # 🔍 เช็คซ้ำจาก project_condo / project_house collection
            if prj_name_th in name_registry or prj_name in name_registry:
                print(f"      ⏭️  Skipped (มีอยู่ใน {collection_name} แล้ว)")
                continue
            
            # Aggregate specs
            built_year = total_units = floors = common_fee = parking = launch_price = project_area = buildings = None
            
            def clean_numeric(val):
                if not val: return None
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(val).replace(',', ''))
                return nums[0] if nums else None

            def convert_to_sqwa(area_str):
                if not area_str: return None
                area_str = str(area_str).replace(",", "").strip()
                total_sqwa = 0
                found = False
                
                # 🔍 1. เช็คแบบ shorthand "ไร่-งาน-วา" (เช่น 3-3-12.34 ไร่)
                shorthand = re.search(r"(\d+)-(\d+)-([\d\.]+)", area_str)
                if shorthand:
                    total_sqwa = (int(shorthand.group(1)) * 400) + (int(shorthand.group(2)) * 100) + float(shorthand.group(3))
                    return float(total_sqwa)

                # 🔍 2. เช็คแบบแยกคำ ไร่/งาน/วา
                rai = re.search(r"([\d\.]+)\s*ไร่", area_str)
                if rai:
                    total_sqwa += float(rai.group(1)) * 400
                    found = True
                ngan = re.search(r"([\d\.]+)\s*งาน", area_str)
                if ngan:
                    total_sqwa += float(ngan.group(1)) * 100
                    found = True
                wa = re.search(r"([\d\.]+)\s*(?:ตารางวา|วา)", area_str)
                if wa:
                    total_sqwa += float(wa.group(1))
                    found = True
                
                if found: return float(total_sqwa)

                # 🔍 3. Fallback: ถ้าไม่มีหน่วยแต่มีตัวเลข
                val = clean_numeric(area_str)
                return float(val) if val else None

            for lead in leads_list:
                if not built_year: built_year = lead.get("zmyh_built_year")
                if not total_units: total_units = lead.get("zmyh_total_units")
                if not floors: floors = lead.get("zmyh_max_floors")
                if not common_fee: common_fee = lead.get("zmyh_common_fee")
                if not parking: parking = lead.get("zmyh_parking")
                if not launch_price: launch_price = lead.get("zmyh_launch_price")
                if not project_area: project_area = lead.get("zmyh_project_area")
                if not buildings: buildings = lead.get("zmyh_num_buildings")
            
            built_date = f"{int(built_year)}-01-01" if built_year and str(built_year).isdigit() else None
            num_floors = clean_numeric(floors)
            num_units = clean_numeric(total_units)
            num_common_fee = clean_numeric(common_fee)
            num_parking = clean_numeric(parking)
            num_launch_price = clean_numeric(launch_price)
            num_area_sqwa = convert_to_sqwa(project_area)
            num_buildings = clean_numeric(buildings)
            
            # เตรียม Specifications JSON (ตัวเลขล้วนๆ)
            specs = {}
            if num_floors: specs["total_floors"] = num_floors
            if num_units: specs["total_units"] = num_units
            if num_parking: specs["parking"] = num_parking
            if num_launch_price: specs["launch_price"] = num_launch_price
            if num_area_sqwa: specs["project_area_square_wa"] = num_area_sqwa
            if num_buildings: specs["number_of_buildings"] = num_buildings
            
            print(f"      📊 Data: Units={num_units}, Floors={num_floors}, Area={num_area_sqwa} sqwa")
            
            form_data = {
                "developer_id": (None, str(developer_id)),
                "name_en": (None, prj_name_en),
                "name_th": (None, prj_name_th),
                "is_active": (None, "1"),
            }
            if built_date: form_data["built_date"] = (None, built_date)
            if num_common_fee: form_data["common_fee"] = (None, str(num_common_fee))
            if num_units: form_data["total_units"] = (None, str(num_units))
            if num_floors: form_data["total_floors"] = (None, str(num_floors))
            if num_parking: form_data["total_parking_slots"] = (None, str(num_parking))
            if num_launch_price: form_data["launch_price"] = (None, str(num_launch_price))
            if num_area_sqwa: form_data["project_area_square_wa"] = (None, str(num_area_sqwa))
            if num_buildings: form_data["number_of_buildings"] = (None, str(num_buildings))
            
            if specs: form_data["specifications_json"] = (None, json.dumps(specs))
            
            api_url = f"{API_BASE_URL}/api/staff/{project_endpoint}"
            try:
                print(f"      🚀 POST -> {api_url}")
                resp = requests.post(api_url, files=form_data, headers=staff_headers, timeout=30)
                if resp.status_code in [200, 201]:
                    result = resp.json()
                    # ดึง Project ID จาก response (data.condo_project.id หรือ data.house_project.id)
                    data = result.get("data", {}) or {}
                    proj_obj = data.get("condo_project") or data.get("house_project") or data
                    created_id = proj_obj.get("id", "?") if isinstance(proj_obj, dict) else "?"
                    print(f"      ✅ Created! {prj_name} → Project ID: {created_id}")
                    project_count += 1

                    import datetime
                    now_iso = datetime.datetime.utcnow().isoformat()

                    # 💾 1. บันทึกข้อมูล Project ลง project_condo / project_house
                    project_doc = {
                        "project_id": created_id,
                        "name_th": prj_name_th,
                        "name_en": prj_name_en,
                        "developer_id": developer_id,
                        "developer_name": dev_name,
                        "type": project_type,
                        "built_year": built_year,
                        "total_units": num_units,
                        "total_floors": num_floors,
                        "common_fee": num_common_fee,
                        "parking": num_parking,
                        "launch_price": num_launch_price,
                        "project_area_square_wa": num_area_sqwa,
                        "specifications": specs,
                        "lead_count": len(leads_list),
                        "synced_at": now_iso,
                    }
                    fs.db.collection(collection_name).document(str(created_id)).set(project_doc)
                    print(f"      📂 Project saved → {collection_name}/{created_id}")

                    # 📎 2. อัปเดต Leads ทุกตัวใน Group ให้ Link กับ Project
                    lead_patch = {
                        "project_id": created_id,
                        "project_type": project_type,
                        "developer_id": developer_id,
                        "project_synced": True,
                    }
                    for lead in leads_list:
                        fs.db.collection("Leads").document(lead["doc_id"]).update(lead_patch)
                    print(f"      🔗 Linked {len(leads_list)} Leads → project_id={created_id}")

                    # อัปเดต memory registry
                    name_registry.add(prj_name_th)
                    name_registry.add(prj_name)
                else:
                    print(f"      ⚠️ Failed: {resp.status_code}")
                    print(f"      📥 Response: {resp.text}")
            except Exception as e:
                print(f"      ❌ API Error: {e}")
            time.sleep(1.5)
        if PROJECT_LIMIT and project_count >= PROJECT_LIMIT: break

    print(f"\n🎉 Sync Complete! Created {project_count} projects.")

if __name__ == "__main__":
    main()
