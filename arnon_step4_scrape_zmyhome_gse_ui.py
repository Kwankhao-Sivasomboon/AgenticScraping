import os
import re
import time
import sys
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()

# ⚙️ Config
FORCE_RE_SCRAPE = False  # 🚩 ตั้งเป็น True ถ้าต้องการทำใหม่ทั้งหมดแม้จะมีข้อมูลแล้ว
TEST_LIMIT = None       # ตั้งเป็น None เพื่อทำทั้งหมด
COLLECTION = "Leads"
GSE_UI_URL = "https://cse.google.com/cse?cx=86685f14ed57d4f5d"

def find_zmyhome_url_gse_ui(page, project_name: str) -> str | None:
    """
    ใช้ Playwright ค้นหาผ่านหน้าเว็บ Google CSE UI โดยตรง (ฟรี)
    """
    print(f"      🔍 GSE UI Search: '{project_name}'")
    try:
        # 1. เข้าหน้า CSE UI (ใช้การพิมพ์แทนการใส่ใน URL Hash เพื่อความชัวร์)
        page.goto(GSE_UI_URL, wait_until="networkidle", timeout=30000)
        
        # ค้นหาช่องค้นหาและพิมพ์
        search_box = page.locator("input.gsc-input")
        search_box.fill(f"zmyhome project {project_name}")
        search_box.press("Enter")
        
        # 2. รอให้ผลลัพธ์ขึ้นและ "Visible" (ไม่ hidden)
        # ใช้สมาธิรอ .gsc-webResult ที่แสดงผลจริง
        page.wait_for_selector(".gsc-webResult", state="visible", timeout=15000)
        page.wait_for_timeout(2000) # รอให้นิ่ง
        
        # 3. ดึงลิงก์
        links = page.evaluate('''() => {
            let results = [];
            let anchors = document.querySelectorAll("a.gs-title");
            for (let a of anchors) {
                if (a.href) results.push(a.href);
            }
            return results;
        }''')
        
        zmyhome_pattern = re.compile(r"https?://(?:www\.)?zmyhome\.com/project/[^/\s?]+", re.IGNORECASE)
        exclude_keywords = ["marker", "search", "filter", "sort", "per-page"]

        for link in links:
            if zmyhome_pattern.match(link):
                if not any(k in link.lower() for k in exclude_keywords):
                    print(f"      ✅ Found URL: {link}")
                    return link
    except Exception as e:
        print(f"      ⚠️ GSE UI Search Error: {e}")
    return None

def scrape_zmyhome_project_page(page, project_url: str) -> dict:
    print(f"      🎭 Playwright Scrape: {project_url}")
    try:
        page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
        try: page.wait_for_selector("ul.info-project__list", timeout=10000)
        except: pass
        
        content = page.content()
        soup = BeautifulSoup(content, "html.parser")
        
        res = {}
        container = soup.find('ul', class_='info-project__list')
        li_items = container.find_all('li') if container else []

        for li in li_items:
            label_tag = li.find('span', class_='small')
            value_tag = li.find('strong', class_=lambda c: c and 'label' in str(c))
            if label_tag and value_tag:
                label, val = label_tag.get_text(strip=True), value_tag.get_text(strip=True)
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
        return res
    except Exception as e:
        print(f"      ❌ Scrape Error: {e}")
        return {}

def main():
    fs = FirestoreService()
    if not fs.db: return
    
    print(f"⏳ Fetching leads...")
    docs = list(fs.db.collection(COLLECTION).get())
    
    projects_map = {}
    skipped = 0
    core_fields = ["zmyh_developer", "zmyh_built_year", "zmyh_total_units", "zmyh_facilities"]

    for doc in docs:
        data = doc.to_dict()
        
        # 🕵️‍♂️ ลอจิก Skip: ทำงานเฉพาะเมื่อไม่ได้สั่ง FORCE_RE_SCRAPE
        if not FORCE_RE_SCRAPE:
            filled = sum(1 for f in core_fields if data.get(f) and data.get(f) != "" and data.get(f) != [])
            if filled >= 3:
                skipped += 1
                continue
                
        p_name = data.get("project_name") or data.get("sheet_ชื่อโครงการ")
        if p_name:
            if p_name not in projects_map: projects_map[p_name] = []
            projects_map[p_name].append(doc)

    print(f"📊 Projects to process: {len(projects_map)} (Skipped: {skipped})")

    with sync_playwright() as p:
        # 📺 เปิดโหมดโชว์หน้าจอ (headless=False) และชะลอการทำงาน (slow_mo) เพื่อให้บอสดูทัน
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_page()
        
        count = 0
        for p_name, p_docs in projects_map.items():
            if TEST_LIMIT and count >= TEST_LIMIT: break
            count += 1
            
            first_data = p_docs[0].to_dict()
            existing_url = first_data.get("zmyh_project_url")
            
            print(f"\n🏢 [{count}] '{p_name}'")
            
            # ลอจิกเลือก URL: ถ้า URL เดิมเป็น 'marker' หรือไม่มี URL เลย ให้หาใหม่
            target_url = None
            if existing_url and "/project/" in existing_url and "marker" not in existing_url:
                print(f"      ♻️ Using valid existing URL: {existing_url}")
                target_url = existing_url
            else:
                if existing_url and "marker" in existing_url:
                    print(f"      🚨 Found bad marker URL, re-searching...")
                target_url = find_zmyhome_url_gse_ui(context, p_name)
            
            if target_url:
                scraped = scrape_zmyhome_project_page(context, target_url)
                if scraped:
                    payload = {"zmyh_scraped": True}
                    for k, v in scraped.items(): payload[f"zmyh_{k}"] = v
                    for d in p_docs: d.reference.update(payload)
                    print(f"      ✅ Success")
                else:
                    print(f"      ⚠️ Scrape empty")
            else:
                print(f"      ⏭️ Not Found")
            
            time.sleep(1)
        
        browser.close()

if __name__ == "__main__":
    main()
