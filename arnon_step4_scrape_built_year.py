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

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()

# ⚙️ ตั้งค่าโหมดทดสอบ
TEST_LIMIT = None 

def scrape_zmyhome_data(project_name, property_type=""):
    """
    1. พิมพ์ทีละวรรคให้จบ
    2. รอ Dropdown แสดงผล (1.5s)
    3. เลือกอันที่คะแนนใกล้เคียงที่สุด (รองรับไทย-อังกฤษ)
    4. ดึงข้อมูลแบบรวดเร็ว
    """
    print(f"      🔎 Searching ON ZmyHome: '{project_name}'")
    
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError as e:
        print(f"      [!] Playwright Error: {e}")
        return None

    res = {}
    target_url = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            Stealth().apply_stealth_sync(context)
            page = context.new_page()

            # 1. เข้าหน้าเว็บ
            page.goto("https://zmyhome.com/project", wait_until="domcontentloaded", timeout=30000)
            
            # จัดการ Cookie (อิงจาก Codegen ของแท้)
            try: page.get_by_role("button", name="ยอมรับทั้งหมด").click(timeout=3000)
            except: pass

            # ฟังก์ชันตัวช่วยปิด Google Ads เด้งขวางหน้าจอ (Vignette Ads) แบบที่เจอใน Codegen
            def close_annoying_ads():
                try:
                    for iframe in page.frames:
                        close_btn = iframe.locator("text='ปิดโฆษณา'").first
                        if close_btn.count() > 0: close_btn.click(timeout=1000)
                        
                        close_en = iframe.locator("[aria-label='Close ad']").first
                        if close_en.count() > 0: close_en.click(timeout=1000)
                except: pass

            close_annoying_ads()

            # 2. แปลไทยกันเหนียว (ถ้าชื่อเป็นอังกฤษ)
            thai_project_name = ""
            if any(c.isalpha() for c in project_name):
                try:
                    from google import genai
                    api_key = os.getenv('GEMINI_API_KEY')
                    if api_key:
                        client = genai.Client(api_key=api_key)
                        prompt = f"Property: '{project_name}'. Give ONLY Thai name used on ZmyHome."
                        resp = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
                        thai_project_name = resp.text.strip().replace("'", "").replace('"', "")
                        print(f"      🌐 Translated: '{thai_project_name}'")
                except Exception as e:
                    print(f"      [!] Translation Error: {e}")

            # 3. เริ่มค้นหาจำลองมนุษย์แบบพิมพ์ทีละวรรค
            search_words = re.split(r'[\s\-]+', project_name.strip())
            search_words = [w for w in search_words if w]
            import difflib
            
            target_text_for_match = ""
            current_query = ""

            for i, word in enumerate(search_words):
                is_last_word = (i == len(search_words) - 1)
                full_word_to_type = word if is_last_word else word + " "
                current_query += full_word_to_type
                
                print(f"      ⌨️ Typing: '{word}'...")
                
                # ถ้ามีโฆษณาแทรกระหว่างพิมพ์ โฟกัสจะหลุด และSpacebarจะกลายเป็นเลื่อนหน้าจอ! ต้องฆ่าโฆษณาก่อน
                close_annoying_ads()
                
                # ใช้ตัวตบตาพิมพ์ข้อความด้วย Vanilla JS + ปลุก jQuery ให้ Dropdown กางโดยไม่เลื่อนจอ
                page.evaluate(f'''(query) => {{
                    return new Promise((resolve) => {{
                        let el = document.getElementById("keyword");
                        if(el) {{
                            el.value = query;
                            // ทะลวงเข้า jQuery ของ ZmyHome ปลุก Dropdown ให้กาง 100% แบบไม่มีการเลื่อนจอ
                            if (window.jQuery && $(el).data('ui-autocomplete')) {{
                                $(el).autocomplete("search", query);
                            }} else if (window.jQuery) {{
                                $(el).trigger("keydown");
                            }}
                        }}
                        setTimeout(resolve, 500); // พักรอให้ JS ทำงาน
                    }});
                }}''', current_query)
                
                page.wait_for_timeout(2500)  # รอ Dropdown กาง

                # ดึงข้อมูล Dropdown
                dropdown_items = page.evaluate('''() => {
                    let results = [];
                    let items = document.querySelectorAll("div.result-detail");
                    for (let n = 0; n < items.length; n++) {
                        let h4 = items[n].querySelector("h4.list-name");
                        let txt = h4 ? h4.innerText : items[n].innerText;
                        if (txt && txt.trim()) results.push({ text: txt.trim() });
                    }
                    return results;
                }''')

                if not dropdown_items:
                    continue # ยังไม่ขึ้นเลย พิมพ์ต่อ

                # กฎเหล็ก: ถ้าตัวเลือกมากกว่า 5 รายการ และยังไม่ถึงคำสุดท้าย -> พิมพ์ต่อเพื่อบีบผลลัพธ์
                if len(dropdown_items) > 5 and not is_last_word:
                    print(f"      ⏳ Many results ({len(dropdown_items)}), typing next word...")
                    continue

                # มี <= 5 รายการ หรือพิมพ์จนหมดคำแล้ว -> เลือกอันที่ดีที่สุด
                best_text, best_score = "", 0
                for item in dropdown_items:
                    txt = item['text']
                    sc_en = difflib.SequenceMatcher(None, project_name.lower(), txt.lower()).ratio()
                    sc_th = difflib.SequenceMatcher(None, thai_project_name.lower(), txt.lower()).ratio() if thai_project_name else 0
                    score = max(sc_en, sc_th)
                    if score > best_score:
                        best_score, best_text = score, txt
                
                # ถ้าคะแนนน้อยมาก (เช่น หาด้วย Eng แต่เว็บคืนค่ามาเป็นภาษาไทย) ให้เชื่อใจผลการค้นหาของ ZmyHome อันดับที่ 1
                if best_score < 0.3:
                    print(f"      ⚠️ Text mismatch score ({best_score:.2f}). Trusting ZmyHome's top result!")
                    best_text = dropdown_items[0]['text']
                    best_score = 1.0 # บังคับให้ผ่าน
                
                print(f"      🎯 Selecting: '{best_text}'")
                target_text_for_match = best_text
                
                # 4. คลิกหัวข้อใน Dropdown
                try:
                    page.get_by_role("heading", name=best_text).first.click(timeout=3000)
                except:
                    try: page.locator(f"h4.list-name:has-text('{best_text}')").first.click(timeout=3000)
                    except: pass
                
                page.wait_for_timeout(3000)
                close_annoying_ads()
                break

            if not target_text_for_match:
                print("      ⌨️ ⚠️ No reliable match found. Skipping.")
                browser.close()
                return None

            best_text = target_text_for_match # ส่งต่อให้ logic ตรวจสอบหน้า Result
            
            # 5. ตรวจสอบว่าตกไปหน้า Result ปลายทางไหน
            target_url = None
            if "/project/" in page.url:
                target_url = page.url
            else:
                print("      🗺️ Landed on search results. Finding exact match...")
                # ตาม Codegen: พยายามดึงลิงก์ที่ตรงชื่อเป๊ะๆ แบบที่บอสคลิก
                try:
                    exact_link = page.get_by_role("link", name=best_text).filter(has_attribute="href").first
                    if exact_link.count() > 0:
                        href = exact_link.get_attribute("href")
                        if href and "/project/" in href:
                            target_url = href if "http" in href else "https://zmyhome.com" + href
                except: pass
                
                # Fallback กรณี role หาไม่เจอ
                if not target_url:
                    result_links = page.locator("span.label a").all()
                    for r_link in result_links:
                        if r_link.evaluate("el => el.innerText").strip() == best_text: 
                            href = r_link.get_attribute("href")
                            if href:
                                target_url = href if "http" in href else "https://zmyhome.com" + href
                                break
            
            if not target_url:
                print(f"      ❌ Could not navigate to project page for '{best_text}'")
                browser.close()
                return None

            # 6. ดึงข้อมูล
            print(f"      ✅ MATCH URL: {target_url}")
            page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            close_annoying_ads() # ฆ่าโฆษณาก่อนดึง UI

            if not target_url:
                print("      ⌨️ ⚠️ No reliable match. Skipping.")
                browser.close()
                return None

            # 6. ดึงข้อมูล
            print(f"      ✅ MATCH URL: {target_url}")
            page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            close_annoying_ads() # ฆ่าโฆษณาก่อนดึง UI

            try: page.wait_for_selector("ul.info-project__list", timeout=5000)
            except: pass
            
            actual_name = page.locator("h1").inner_text().strip()
            print(f"      🏢 Verify: '{actual_name}'")
            
            # ตรวจสอบขั้นสุดท้าย (65% เพื่อให้ คันทรี่ คอมเพล็กซ์ ผ่านได้)
            if difflib.SequenceMatcher(None, project_name.lower(), actual_name.lower()).ratio() < 0.55 and project_name.lower() not in actual_name.lower():
                 print(f"      ❌ Match Failed! ({actual_name})")
                 browser.close()
                 return None

            soup = BeautifulSoup(page.content(), 'html.parser')
            browser.close()
            
            # -- Parse Specs --
            container = soup.find('ul', class_='info-project__list')
            li_items = container.find_all('li') if container else []
            for li in li_items:
                label_tag = li.find('span', class_='small')
                value_tag = li.find('strong', class_=lambda c: c and 'label' in str(c))
                if label_tag and value_tag:
                    label, val = label_tag.get_text(strip=True), value_tag.get_text(strip=True)
                    if "ปีที่สร้างเสร็จ" in label: res["built_year"] = int(re.search(r'(\d{4})', val).group(1)) if re.search(r'(\d{4})', val) else None
                    elif "ราคาเปิดตัว" in label: res["launch_price"] = val
                    elif "ยูนิตทั้งหมด" in label: res["total_units"] = val
                    elif "พื้นที่จอดรถ" in label: res["parking"] = val
                    elif "จำนวนชั้น" in label: res["max_floors"] = val
                
                txt = li.get_text(strip=True)
                if "ผู้พัฒนา :" in txt: res["developer"] = txt.replace("ผู้พัฒนา :", "").strip()
            
            facs = [s.get_text(strip=True) for s in soup.find('div', class_='facality').find_all('span', class_='label')] if soup.find('div', class_='facality') else []
            if facs: res["facilities"] = facs
            
            return res if res else None

    except Exception as e:
        print(f"      [!] Error: {e}")
        return None

def main():
    print(f"🔐 Firestore: Initializing...")
    fs = FirestoreService()
    docs = fs.db.collection("Leads").get()
    projects_map = {}
    skipped = 0

    for doc in docs:
        data = doc.to_dict()
        if data.get("zmyh_built_year"):
            skipped += 1
            continue
            
        p_name = data.get("project_name") or data.get("sheet_ชื่อโครงการ") or (data.get("evaluation", {}).get("project_name") if isinstance(data.get("evaluation"), dict) else None)
        if not p_name or str(p_name).strip().lower() in ["none", "null", ""]: continue
        
        p_name = str(p_name).strip()
        if p_name not in projects_map: projects_map[p_name] = []
        projects_map[p_name].append(doc)

    print(f"📊 Projects: {len(projects_map)} (Skipped: {skipped})")

    p_count = 0
    for p_name, p_docs in projects_map.items():
        if TEST_LIMIT and p_count >= TEST_LIMIT: break
        print(f"🏢 Project: {p_name} ({len(p_docs)} leads)")
        
        scraped = scrape_zmyhome_data(p_name)
        if scraped:
            payload = {f"zmyh_{k}": v for k, v in scraped.items()}
            print(f"   ✅ Found Specs: {list(payload.keys())}")
            for doc in p_docs: doc.reference.update(payload)
        else: print(f"   ❌ No data.")
        
        p_count += 1
        time.sleep(1)

if __name__ == "__main__":
    main()
