import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Primary: DuckDuckGo 
try:
    from duckduckgo_search import DDGS
    USE_DDG = True
except ImportError:
    USE_DDG = False

# Fallback: Google Search API
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
TEST_LIMIT = None  # แก้เป็น None เพื่อรันทั้งหมด

def scrape_zmyhome_data(project_name, property_type=""):
    """
    ใช้ Playwright เข้าเว็บไซต์ zmyhome.com/project โดยตรง 
    พิมพ์ค้นหา และกดเลือกผลลัพธ์
    """
    print(f"      🔎 Searching ON ZmyHome directly: '{project_name}' (Type: {property_type})")
    
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        print(f"      [!] Playwright/stealth Error: {e}")
        return None

    res = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            Stealth().apply_stealth_sync(context)
            page = context.new_page()

            # 1. เข้าสู่หน้าแรก ZmyHome เพื่อให้ได้ Session / Cookies / Cloudflare validation
            print(f"      🤖 [ZmyHome] Initiating Session...")
            page.goto("https://zmyhome.com/project", wait_until="networkidle", timeout=30000)
            
            # --- จัดการ Cookie / Pop-up ---
            try:
                cookie_button = page.locator("button:has-text('ยอมรับ'), button:has-text('Accept'), .btn-cookie")
                if cookie_button.is_visible():
                    cookie_button.click(timeout=3000)
            except:
                pass

            # 2. ฟังก์ชันเรียก API ค้นหาของ ZmyHome โดยตรงผ่านเบราว์เซอร์
            def search_api(term):
                # ใช้ JS Fetch ยิงตรงไปที่ระบบค้นหา (เหมือนคนพิมพ์ในช่องเป๊ะๆ แต่เร็วกว่า)
                try:
                    js_code = f"""async () => {{
                        let res = await fetch('/search/load-point?term=' + encodeURIComponent("{term}"), {{
                            headers: {{ 'X-Requested-With': 'XMLHttpRequest' }}
                        }});
                        let text = await res.text();
                        try {{ return JSON.parse(text); }} 
                        catch(e) {{ return null; }}
                    }}"""
                    return page.evaluate(js_code)
                except Exception as e:
                    print(f"      [!] API Fetch Error: {e}")
                    return []

            target_url = None
            
            # --- 3. ฟังก์ชันลองค้นหาแบบหลาย Step (Full Name -> Short Name) ---
            def retry_search(name):
                print(f"      📡 Querying internal API for: '{name}'")
                results = search_api(name)
                url = extract_url(results, name)
                if url: return url
                
                # ถ้าไม่เจอ ลองตัดเหลือแค่ 2 คำแรก (Smart Truncation)
                words = name.split()
                if len(words) > 2:
                    short_name = " ".join(words[:2])
                    print(f"      📡 Retrying with shorter name: '{short_name}'")
                    results = search_api(short_name)
                    return extract_url(results, short_name)
                return None

            def extract_url(results, search_term):
                if not results or not isinstance(results, list): return None
                # 1. หาแบบเป๊ะๆ ใน label
                for item in results:
                    label = str(item.get("label", ""))
                    if search_term.lower() in label.lower() and ('/project/' in str(item.get("slug", "")) or '/project/' in str(item.get("url", ""))):
                        return item.get("url") or item.get("slug")
                
                # 2. ถ้าไม่เจอ ให้เอาอันแรกสุดที่เป็นหมวด "โครงการ" (มักจะตรงที่สุด)
                for item in results:
                    slug = str(item.get("slug", ""))
                    url = str(item.get("url", ""))
                    if '/project/' in slug or '/project/' in url:
                        return url if url else slug
                return None

            # เริ่มลุย!
            target_url = retry_search(project_name)

            # --- FALLBACK: แปลเป็นไทยแล้วลุยต่อ ---
            if not target_url and any(c.isalpha() for c in project_name):
                print(f"      🔄 [Fallback] English API search failed. Translating...")
                try:
                    from google import genai
                    api_key = os.getenv('GEMINI_API_KEY')
                    if api_key:
                        client = genai.Client(api_key=api_key)
                        prompt = f"Name of property/condo: '{project_name}'. Give ONLY the main Thai brand name as used on ZmyHome. No phase, no locations. Example: 'The Metropolis Samrong' -> 'เดอะ เมโทรโพลิส'"
                        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                        thai_name = response.text.strip()
                        print(f"      🌐 Translated to: '{thai_name}'")
                        target_url = retry_search(thai_name)
                except Exception as ex:
                    print(f"      [!] Translation fallback failed: {ex}")

            # --- 4. ULTIMATE FALLBACK: ถ้าใช้ API ทุกวิถีทางแล้วยังไม่เจอ ให้ลองพิมพ์ค้นหาจริงผ่าน UI ---
            if not target_url:
                print(f"      ⌨️ [Ultimate Fallback] Trying real UI Search for: '{project_name}'")
                try:
                    # พิมพ์ใหม่ผ่าน UI
                    page.fill("input#keyword", "")
                    page.fill("input#keyword", project_name)
                    page.press("input#keyword", "Enter")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(3000)
                    
                    # เลื่อนหน้าเล็กน้อยเผื่อปุ่มแอบ
                    page.mouse.wheel(0, 500)
                    page.wait_for_timeout(1000)

                    # หาล่าสุดในผลลัพธ์หน้าจอ (หาแบบ Fuzzy มากขึ้น)
                    links = page.locator("span.label a, .auto-result a").all()
                    for link in links:
                        text = link.inner_text().strip()
                        # ถ้าชื่อมีคำหลัก 2 คำแรกตรงกัน ให้ถือว่าใช่!
                        main_keywords = [w.lower() for w in project_name.split() if len(w) > 2][:2]
                        if all(k in text.lower() for k in main_keywords):
                            target_url = link.get_attribute("href")
                            if target_url: 
                                print(f"      🎯 Found via UI Fuzzy Search: {target_url} (Matched: {text})")
                                break
                    
                    # ถ้ายังไม่เจออีก... ลองใช้ "ชื่อสั้น" ที่ Gemini ช่วยคิดให้
                    if not target_url:
                        print(f"      🤖 Asking Gemini for the 'Shortest Common Name' on ZmyHome...")
                        try:
                            from google import genai
                            client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
                            prompt = f"What is the shortest brand name for this condo in Thai that I should search on ZmyHome? Project: '{project_name}'. Give ONLY the Thai name. Example: 'The Coast Bangkok' -> 'เดอะ โคสท์'"
                            resp = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                            short_thai = resp.text.strip()
                            print(f"      ⌨️ Final Attempt with Short Thai: '{short_thai}'")
                            page.fill("input#keyword", "")
                            page.fill("input#keyword", short_thai)
                            page.press("input#keyword", "Enter")
                            page.wait_for_timeout(4000)
                            
                            # คว้าอันแรกสุดที่เจอเลย (มักจะเป็นหน้า Project หลัก)
                            first_link = page.locator("span.label a, .auto-result a").first
                            if first_link.is_visible():
                                target_url = first_link.get_attribute("href")
                                print(f"      🎯 Found via Short Thai Search: {target_url}")
                        except: pass
                except Exception as ui_ex:
                    print(f"      [!] UI Fallback error: {ui_ex}")

            if not target_url:
                print(f"      ⚠️ ไม่พบโครงการ '{project_name}' หลังจากพยายามทุกวิธีแล้ว")
                browser.close()
                return None

            if not target_url.startswith("http"):
                target_url = "https://zmyhome.com" + target_url

            print(f"      ✅ MATCH Project URL: {target_url}")

            # 6. เข้าไปหน้าโครงการจริงเพื่อดึงข้อมูล
            try:
                # เปลี่บนเป็น domcontentloaded เผื่อเว็บ ZmyHome มี Ads หมุนไม่หยุดจนเจอ Timeout
                page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"      ⚠️ Page loaded with warnings (proceeding to extract data): {e}")
            
            html_content = page.content()
            browser.close()
            
            # -- ดึงข้อมูลผ่าน BeautifulSoup --
            soup = BeautifulSoup(html_content, 'html.parser')
            
            container = soup.find('ul', class_='info-project__list')
            items = container.find_all('li') if container else soup.find_all('li')
            
            for li in items:
                label_tag = li.find('span', class_='small')
                value_tag = li.find('strong', class_=lambda c: c and 'label' in str(c))
                if label_tag and value_tag:
                    label = label_tag.get_text(strip=True)
                    val = value_tag.get_text(strip=True)
                    
                    if "ปีที่สร้างเสร็จ" in label:
                        match = re.search(r'(\d{4})', val)
                        if match: res["built_year"] = int(match.group(1))
                    elif "ราคาเปิดตัว" in label: res["launch_price"] = val
                    elif "ค่าส่วนกลาง" in label: res["common_fee"] = val
                    elif "พื้นที่โครงการ" in label: res["project_area"] = val
                    elif "จำนวนตึก" in label: res["num_buildings"] = val
                    elif "จำนวนชั้น" in label: res["max_floors"] = val
                    elif "ยูนิตทั้งหมด" in label: res["total_units"] = val
                    elif "พื้นที่จอดรถ" in label: res["parking"] = val
                
                # พิเศษ: หา "ผู้พัฒนา :" (บางทีไม่มี span.small)
                text_content = li.get_text(strip=True)
                if "ผู้พัฒนา :" in text_content:
                    dev_name = text_content.replace("ผู้พัฒนา :", "").strip()
                    res["developer"] = dev_name
            
            # Facilities
            facilities = []
            # ค้นหาด้วยคลาสที่พิมพ์ผิดของ ZmyHome ('facality')
            fac_container = soup.find('div', class_='facality')
            if fac_container:
                # หา span ที่มี class 'label' ทั้งหมด ซึ่งจะครอบคลุมทั้งใน list ปกติ และที่ซ่อนอยู่ใน div.more
                for span in fac_container.find_all('span', class_='label'):
                    name = span.get_text(strip=True)
                    if name: facilities.append(name)
            if facilities: res["facilities"] = facilities
            
            return res if res else None

    except Exception as e:
        print(f"      [!] Playwright Direct Scrape Error: {e}")
        return None

def main():
    print(f"🔐 Firestore: Initializing...")
    fs = FirestoreService()
    docs = fs.db.collection("Leads").get()
    # 1. จัดกลุ่มเอกสารทั้งหมดตามชื่อโครงการ และกรองอันที่มีข้อมูลแล้วทิ้ง
    projects_map = {}
    skipped_count = 0

    for doc in docs:
        data = doc.to_dict()
        
        # ถ้ารายการไหนเคยดึงได้ปีและ facilities แล้ว ให้ข้ามไปเลย
        if data.get("zmyh_built_year") and data.get("zmyh_facilities"):
            skipped_count += 1
            continue
            
        project_name = data.get("project_name") or data.get("sheet_ชื่อโครงการ") or (data.get("evaluation", {}).get("project_name") if isinstance(data.get("evaluation"), dict) else None)
        
        if not project_name or str(project_name).strip().lower() in ["none", "null", ""]: 
            continue
            
        project_name = str(project_name).strip()
        property_type = data.get("sheet_ประเภททรัพย์", "")

        if project_name not in projects_map:
            projects_map[project_name] = {"property_type": property_type, "docs": []}
        projects_map[project_name]["docs"].append(doc)

    print(f"📊 Total leads to process: {sum(len(v['docs']) for v in projects_map.values())} in {len(projects_map)} unique projects (Skipped {skipped_count} already scraped)")

    # 2. วนลูป Scrape ทีละ "โครงการ" (ไม่ใช่ทีละ Lead)
    updated_total = 0
    processed_count = 0
    
    for project_name, info in projects_map.items():
        if TEST_LIMIT and processed_count >= TEST_LIMIT: break

        doc_count = len(info['docs'])
        print(f"🏢 Project: {project_name} (Updating {doc_count} leads)")
        
        # ปรับให้ส่ง property_type ที่คลีนแล้ว (เช่น 'คอนโด', 'แนวราบ') ไม่ใช่ 'คอนโดมือ 2'
        p_type = info['property_type']
        if "คอนโด" in p_type: p_type = "คอนโด"
        elif any(x in p_type for x in ["บ้าน", "ทาวน์", "ราบ"]): p_type = "แนวราบ"
        else: p_type = "" # ถ้าไม่แน่ใจ ไม่กรองจะดีกว่า

        scraped = scrape_zmyhome_data(project_name, p_type)
        
        if scraped:
            update_payload = {f"zmyh_{k}": v for k, v in scraped.items()}
            print(f"   ✅ Found Specs: {list(update_payload.keys())}")
            
            # อัปเดตทันทีรายโครงการ! 
            for doc in info['docs']:
                try:
                    doc.reference.update(update_payload)
                except Exception as e:
                    print(f"      [!] Update failed for {doc.id}: {e}")
            updated_total += doc_count
            print(f"   🔥 [Real-time Update] Saved {doc_count} leads to Firestore.")
        else:
            print(f"   ❌ No data found for project {project_name}.")
        
        processed_count += 1
        time.sleep(2)

    print(f"\n✅ Scraping finished. Total leads updated: {updated_total}")

if __name__ == "__main__":
    main()
