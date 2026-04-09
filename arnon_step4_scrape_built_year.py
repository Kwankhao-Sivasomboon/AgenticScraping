import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Primary: DuckDuckGo (ไม่มี Rate Limit เหมือน Google)
try:
    from duckduckgo_search import DDGS
    USE_DDG = True
except ImportError:
    USE_DDG = False

# Fallback: Google Search
try:
    from googlesearch import search as google_search
    USE_GOOGLE = True
except ImportError:
    USE_GOOGLE = False

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()

# ⚙️ ตั้งค่าโหมดทดสอบ: ใส่จำนวนรายการที่ต้องการ หรือ None เพื่อรันทั้งหมด
TEST_LIMIT = 1  # แก้เป็น None เพื่อรันทั้งหมด

def search_with_playwright(query):
    """
    ใช้ Playwright + Stealth เปิด Browser จริงเพื่อค้นหาบน Google
    เป็น Fallback สุดท้ายเมื่อ DuckDuckGo และ Google API โดน Block
    """
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import stealth_sync
    except ImportError:
        print("      [!] Playwright/stealth ไม่ได้ติดตั้ง: pip install playwright playwright-stealth")
        return []

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            stealth_sync(page)

            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            print(f"      🤖 [Playwright] Opening: {search_url}")
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            # ดึง URL ทั้งหมดจากผลลัพธ์ Google
            links = page.evaluate("""() => {
                let anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors.map(a => a.href).filter(h => h.startsWith('http') && !h.includes('google'));
            }""")

            results = [l for l in links if l]
            browser.close()
            print(f"      🤖 [Playwright] พบ {len(results)} ลิงก์")
    except Exception as e:
        print(f"      [!] Playwright search error: {e}")

    return results

def get_search_results(query, max_results=10):
    """คืน list ของ URL จาก DuckDuckGo → Google → Playwright (fallback chain)"""
    results = []
    if USE_DDG:
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    href = r.get("href", "")
                    if href:
                        results.append(href)
            if results:
                return results
        except Exception as e:
            print(f"      [!] DuckDuckGo error: {e}")
    if USE_GOOGLE:
        try:
            for j in google_search(query, num_results=max_results, lang="th"):
                results.append(j)
        except Exception as e:
            print(f"      [!] Google search error: {e}")
    if results:
        return results

    # สุดท้าย: ใช้ Playwright เปิด Browser จริงค้นบน Google
    print("      🔄 ลองใช้ Playwright Browser เป็น fallback สุดท้าย...")
    results = search_with_playwright(query)
    return results


def scrape_zmyhome_data(project_name):
    query = f'site:zmyhome.com "{project_name}" โครงการ'
    url = None

    try:
        engine = "DuckDuckGo" if USE_DDG else "Google"
        print(f"      \U0001f50e Searching {engine}: '{query}'")
        time.sleep(random.uniform(1.0, 3.0))
        result_count = 0
        for count, j in enumerate(get_search_results(query)):
            result_count += 1
            is_valid_zmyhome = "zmyhome.com" in j.lower()
            is_project_page = any(x in j.lower() for x in ["/project/", "/condo/", "/house/", "/townhome/", "/townhouse/"])
            is_generic_list = any(x in j.lower() for x in ["/project-list/", "/search/", "?search", "/projects-for-sale"])
            status = "\u2705 MATCH" if (is_valid_zmyhome and is_project_page and not is_generic_list) else f"\u26d4 SKIP (zmyhome={is_valid_zmyhome}, project_page={is_project_page}, generic={is_generic_list})"
            print(f"      \U0001f517 [{count+1}] {j}")
            print(f"           \u2192 {status}")
            if is_valid_zmyhome and is_project_page and not is_generic_list:
                url = j
                break
        if result_count == 0:
            print("      \u26a0\ufe0f  \u0e04\u0e37\u0e19 0 \u0e1c\u0e25 \u2014 \u0e2d\u0e32\u0e08\u0e42\u0e14\u0e19 Rate Limit \u0e2b\u0e23\u0e37\u0e2d IP \u0e16\u0e39\u0e01 Block")
        elif not url:
            print(f"      \u26a0\ufe0f  \u0e04\u0e37\u0e19 {result_count} \u0e1c\u0e25 \u0e41\u0e15\u0e48\u0e44\u0e21\u0e48\u0e21\u0e35 ZmyHome project URL \u0e15\u0e23\u0e07")
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "Too Many Requests" in err_msg:
            raise
        print(f"      [!] Search error: {e}")
        return None

    if not url:
        return None

    print(f"      🌐 Target ZmyHome URL: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, 'html.parser')
            result = {}
            
            # เจาะจงหาคลาส ul เฉพาะของข้อมูลโครงการเลย เพื่อความชัวร์ที่สุด
            container = soup.find('ul', class_='info-project__list')
            search_items = container.find_all('li') if container else soup.find_all('li', class_=lambda c: c and 'info-project__item' in c)
            
            # ถ้าหาไม่เจอจริงๆ ขอกวาด li ทั้งหมด
            if not search_items:
                search_items = soup.find_all('li')

            for li in search_items:
                # ลองดึงจาก span.small และ strong.label ตรงๆ ตามโครงสร้าง HTML ของ ZmyHome
                label_tag = li.find('span', class_='small')
                value_tag = li.find('strong', class_=lambda c: c and 'label' in str(c))
                
                label = ""
                val_text = ""
                
                if label_tag and value_tag:
                    label = label_tag.get_text(strip=True)
                    val_text = value_tag.get_text(strip=True)
                else:
                    # Fallback: แยกคำ
                    raw_txt = li.get_text(separator='|', strip=True)
                    parts = [p.strip() for p in raw_txt.split('|') if p.strip()]
                    if len(parts) >= 2:
                        label = parts[0]
                        val_text = " ".join(parts[1:])
                
                if not label or not val_text or val_text.upper() == "N/A" or val_text == "-":
                    continue
                
                print(f"      📍 Found Section: [{label}] -> {val_text}")
                    
                if "ปีที่สร้างเสร็จ" in label or "สร้างเสร็จปี" in label:
                    year_match = re.search(r'(\d{4})', val_text)
                    if year_match:
                        y = int(year_match.group(1))
                        if y > 2400: y -= 543
                        result["built_year"] = y
                elif "จำนวนตึก" in label:
                    m = re.search(r'(\d+)', val_text)
                    if m: result["num_buildings"] = int(m.group(1))
                elif "จำนวนชั้น" in label:
                    m = re.search(r'(\d+)', val_text)
                    if m: result["max_floors"] = int(m.group(1))
                elif "ยูนิตทั้งหมด" in label:
                    m = re.search(r'(\d+)', val_text.replace(',', ''))
                    if m: result["total_units"] = int(m.group(1))
                elif "พื้นที่จอดรถ" in label:
                    result["parking"] = val_text
                elif "ค่าส่วนกลาง" in label:
                    result["common_fee"] = val_text
                elif "ราคาเปิดตัว" in label:
                    result["launch_price"] = val_text

            # --- ดึง Facility List จาก div.facality ---
            fac_div = soup.find('div', class_=lambda c: c and 'facality' in c)
            if fac_div:
                fac_ul = fac_div.find('ul', class_=lambda c: c and 'fac-icon' in str(c))
                if fac_ul:
                    facilities = []
                    for li in fac_ul.find_all('li'):
                        label_span = li.find('span', class_='label')
                        if label_span:
                            fac_text = label_span.get_text(strip=True)
                            if fac_text:
                                facilities.append(fac_text)
                    if facilities:
                        result["facilities"] = facilities
                        print(f"      🏊 Facilities found: {facilities}")

            if result:
                print(f"      🎉 Final Scraped Result: {result}")
                return result
                
            # Fallback Regex สุดท้ายถ้าไม่เจอในตาราง
            all_text = soup.get_text(separator=' ')
            match = re.search(r'(?:ปีที่สร้างเสร็จ|สร้างเสร็จปี).*?(\d{4})', all_text)
            if match:
                y = int(match.group(1))
                if y > 2400: y -= 543
                return {"built_year": y}
                
    except Exception as e:
        print(f"      [!] Error scraping {url}: {e}")
        
    return None

def main():
    fs = FirestoreService()
    mode_text = f"TEST MODE (จำกัดแค่ {TEST_LIMIT} รายการ)" if TEST_LIMIT else "FULL MODE (ทั้งหมด)"
    print(f"🚀 เริ่มสแกน ZmyHome [{mode_text}]...")
    lead_docs = fs.db.collection("Leads").stream()
    count_updated = 0
    count_processed = 0
    for lead_doc in lead_docs:
        prop_id = lead_doc.id
        lead_ref = lead_doc.reference
        lead_data = lead_doc.to_dict()

        if lead_data.get("zmyh_built_year") and lead_data.get("zmyh_total_units"):
            continue
            
        project_name = lead_data.get("sheet_ชื่อโครงการ")
        if not project_name or str(project_name).strip().lower() in ["none", "null", "", "-", "ไม่ระบุ"]:
            eval_data = lead_data.get("evaluation", {})
            if isinstance(eval_data, dict):
                project_name = eval_data.get("project_name")
        if not project_name or str(project_name).strip().lower() in ["none", "null", "", "-", "ไม่ระบุ"]:
            continue
            
        print(f"🏢 Doc: {prop_id} | Project: {project_name}")
        try:
            scraped_data = scrape_zmyhome_data(project_name)
            if scraped_data:
                print(f"   🎉 Success! Updated with ZmyHome Fallback Data.")
                update_payload = {f"zmyh_{k}": v for k, v in scraped_data.items()}
                lead_ref.update(update_payload)
                count_updated += 1
            else:
                print(f"   ❌ No data found on ZmyHome page.")
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "Too Many Requests" in err_msg:
                print(f"   ⚠️ Error 429! Backing off for 60s...")
                time.sleep(60)
            else:
                print(f"   ❌ Error: {e}")
        
        count_processed += 1
        if TEST_LIMIT and count_processed >= TEST_LIMIT:
            print(f"\n✋ หยุด: ครบ {TEST_LIMIT} รายการตาม TEST_LIMIT แล้ว")
            break

        sleep_time = random.randint(5, 12)
        print(f"   ⏳ Waiting {sleep_time}s...")
        time.sleep(sleep_time)

    print(f"✅ Scraping finished. Total ZmyHome fallback records: {count_updated}")

if __name__ == "__main__":
    main()
