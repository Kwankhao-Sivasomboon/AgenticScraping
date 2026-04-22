import os
import re
import time
import sys
import json
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# 🚀 SerpApi Library
try:
    from serpapi import GoogleSearch
except ImportError:
    print("❌ กรุณารัน: pip install google-search-results")
    sys.exit(1)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()

# ⚙️ Config
TEST_LIMIT = 231 
COLLECTION = "Leads"
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

def find_zmyhome_url_serp(project_name: str) -> str | None:
    if not SERPAPI_KEY:
        print("      ⚠️ ERROR: SERPAPI_KEY หายไปจาก .env")
        return None

    query = f"site:zmyhome.com/project {project_name}"
    zmyhome_pattern = re.compile(r"https?://(?:www\.)?zmyhome\.com/project/[^/\s?]+", re.IGNORECASE)
    exclude_keywords = ["marker", "search", "filter", "sort", "per-page"]

    print(f"      🐍 SerpApi Search: '{project_name}'")
    params = {"q": query, "api_key": SERPAPI_KEY, "engine": "google", "num": 5}
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        organic_results = results.get("organic_results", [])
        for r in organic_results:
            link = r.get("link", "")
            if zmyhome_pattern.match(link):
                if not any(k in link.lower() for k in exclude_keywords):
                    print(f"      ✅ Found URL: {link}")
                    return link
    except Exception as e:
        print(f"      ❌ Search Error: {e}")
    return None

def scrape_zmyhome_project_page(project_url: str) -> dict:
    print(f"      🎭 Playwright: Extracting {project_url}...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
            
            # รอให้คอนเทนเนอร์หลักขึ้น
            try: page.wait_for_selector("ul.info-project__list", timeout=10000)
            except: pass
            
            content = page.content()
            soup = BeautifulSoup(content, "html.parser")
            browser.close()
            
            res = {}
            container = soup.find('ul', class_='info-project__list')
            li_items = container.find_all('li') if container else []

            for li in li_items:
                label_tag = li.find('span', class_='small')
                value_tag = li.find('strong', class_=lambda c: c and 'label' in str(c))
                
                if label_tag and value_tag:
                    label = label_tag.get_text(strip=True)
                    val   = value_tag.get_text(strip=True)
                    if "ปีที่สร้างเสร็จ" in label:
                        m = re.search(r'(\d{4})', val)
                        res["built_year"] = m.group(1) if m else ""
                    elif "ราคาเปิดตัว"  in label: res["launch_price"]   = val
                    elif "ยูนิตทั้งหมด" in label: res["total_units"]    = val
                    elif "พื้นที่จอดรถ" in label: res["parking"]        = val
                    elif "จำนวนชั้น"    in label: res["max_floors"]     = val
                    elif "ค่าส่วนกลาง"  in label: res["common_fee"]     = val
                    elif "พื้นที่โครงการ" in label: res["project_area"] = val
                    elif "จำนวนตึก"     in label: res["num_buildings"]  = val

                txt = li.get_text(strip=True)
                if "ผู้พัฒนา :" in txt:
                    dev_val = txt.replace("ผู้พัฒนา :", "").strip()
                    if not re.search(r'\d{4}', dev_val): res["developer"] = dev_val

            fac_div = soup.find('div', class_=re.compile(r'facality|facility', re.I))
            if fac_div:
                blacklist = ["บ้าน", "ขาย", "เช่า", "มือสอง", "เจ้าของขายเอง", "คอนโด", "โครงการ", "ทาวน์โฮม", "ที่ดิน"]
                facs = [s.get_text(strip=True) for s in fac_div.find_all('span', class_='label') 
                        if s.get_text(strip=True) and not any(b in s.get_text(strip=True) for b in blacklist)]
                if facs: res["facilities"] = list(set(facs))

            res["project_url"] = project_url
            return res if res else {}
    except Exception as e:
        print(f"      ❌ Playwright Error: {e}")
        return {}

def main():
    fs = FirestoreService()
    if not fs.db: return
    
    print(f"⏳ Fetching leads for processing...")
    docs = list(fs.db.collection(COLLECTION).get())
    
    projects_map = {}
    skipped = 0
    
    # ฟิลด์หลักที่เราต้องการเช็คว่ามีข้อมูลหรือยัง
    core_fields = [
        "zmyh_developer", "zmyh_built_year", "zmyh_total_units", 
        "zmyh_facilities", "zmyh_launch_price", "zmyh_max_floors"
    ]

    for doc in docs:
        data = doc.to_dict()
        
        # 🕵️‍♂️ ลอจิก Skip ขั้นเทพ: นับจำนวนฟิลด์ที่มีข้อมูลจริง
        filled_count = 0
        for field in core_fields:
            val = data.get(field)
            if val and val != "" and val != []:
                filled_count += 1
        
        # ถ้ามีข้อมูลเกินครึ่ง (4 จาก 6 ฟิลด์) ให้ถือว่า OK แล้ว
        if filled_count >= 4:
            skipped += 1
            continue
            
        p_name = data.get("project_name") or data.get("sheet_ชื่อโครงการ")
        if not p_name: continue
        
        if p_name not in projects_map: projects_map[p_name] = []
        projects_map[p_name].append(doc)

    print(f"📊 Projects needing work: {len(projects_map)} (Skipped already sufficient: {skipped})")

    count = 0
    for p_name, p_docs in projects_map.items():
        if TEST_LIMIT and count >= TEST_LIMIT: break
        count += 1
        
        # ดึง data จาก doc แรกในกลุ่มมาเช็ค URL
        first_data = p_docs[0].to_dict()
        existing_url = first_data.get("zmyh_project_url")
        
        print(f"\n🏢 [{count}] '{p_name}'")
        
        target_url = None
        if existing_url and "/project/" in existing_url:
            print(f"      ♻️ Using existing URL: {existing_url}")
            target_url = existing_url
        else:
            target_url = find_zmyhome_url_serp(p_name)
            
        if target_url:
            scraped = scrape_zmyhome_project_page(target_url)
            if scraped:
                payload = {"zmyh_scraped": True}
                for k, v in scraped.items(): payload[f"zmyh_{k}"] = v
                for d in p_docs: d.reference.update(payload)
                print(f"      ✅ Success")
            else:
                print(f"      ⚠️ Scrape empty")
        else:
            print(f"      ⏭️ URL Not Found")
        
        time.sleep(1)

if __name__ == "__main__":
    main()
