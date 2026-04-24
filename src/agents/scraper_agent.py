import os
import time
import random
import re
from datetime import datetime
from urllib.parse import quote
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from src.config import MAX_ITEMS_PER_RUN, SKIP_KEYWORDS, MAX_PRICE_LIMITS, SHOW_BROWSER

class ScraperAgent:
    def __init__(self):
        self.use_proxy = os.getenv('USE_PROXY', 'false').lower() == 'true'
        self.proxy_server = os.getenv('PROXY_SERVER')
        self.proxy_username = os.getenv('PROXY_USERNAME')
        self.proxy_password = os.getenv('PROXY_PASSWORD')
        self.username = os.getenv('LIVING_INSIDER_USERNAME')
        self.password = os.getenv('LIVING_INSIDER_PASSWORD')
        self.state_file = "playwright_state.json"
        
        from src.services.firestore_service import FirestoreService
        self.firestore = FirestoreService()

    def random_sleep(self, min_seconds=2, max_seconds=5):
        time.sleep(random.uniform(min_seconds, max_seconds))

    def close_banners(self, page):
        """เคลียร์สิ่งกีดขวาง (Popup/Ads) ให้บอทคลิกเมนูหลักได้ โดยไม่ไปซ่อนกล่องค้นหา"""
        try:
            page.evaluate("""() => {
                // 1. กดปุ่มปิดโฆษณาที่ชัดเจน
                const closeSelectors = [
                    '.btn-close', '.close', '#popup-close', '[onclick*="closeBanner"]', 
                    '.modal-header .close', '.modal-footer .btn-secondary', '[aria-label="Close"]'
                ];
                closeSelectors.forEach(s => {
                    document.querySelectorAll(s).forEach(btn => {
                        try { btn.click(); } catch(e) {}
                    });
                });

                // 2. ซ่อนเฉพาะโฆษณา/ตัวคัดกรองที่บังจอจริงๆ (ไม่ซ่อน .modal ทั้งหมด เพราะกล่องค้นหาอาจเป็น modal)
                const adSelectors = [
                    '.sp-container', '.listing-keep-modal', '#collection-modal', 
                    '.popup-ads', '.ads-overlay', '#pds-modal'
                ];
                adSelectors.forEach(s => {
                    document.querySelectorAll(s).forEach(el => {
                        try { el.style.setProperty('display', 'none', 'important'); } catch(e) {}
                    });
                });

                // 3. ปลดล็อก Body (เผื่อเว็บค้างท่า Scroll-lock)
                document.body.classList.remove('modal-open');
                document.body.style.overflow = 'auto';
                document.body.style.pointerEvents = 'auto';
            }""")
        except: pass

    def login(self, page, context):
        """จัดการ Login ทั้งแบบกรอกใหม่ และแบบเลือกจากประวัติ (History)"""
        if not self.username or not self.password:
            print("⚠️ [Login] ไม่พบข้อมูล Username/Password ใน Config")
            return

        print("🌐 [Login] กำลังเข้าหน้าจัดการประกาศ...")
        page.goto('https://www.livinginsider.com/member_istock.php', wait_until='domcontentloaded', timeout=60000)
        self.random_sleep(2, 4)
        
        # 1. เช็คว่าล็อกอินค้างไว้อยู่แล้วหรือไม่
        if page.locator("#btn_dropdown_ownertype").is_visible() or page.locator("a[href*='logout']").is_visible():
            print("✅ [Login] เซสชันยังใช้งานได้อยู่ ไม่ต้องล็อกอินใหม่")
            return

        print("🔑 [Login] เซสชันหมดอายุ กำลังเริ่มกระบวนการเข้าสู่ระบบ...")
        try:
            # 2. ตรวจสอบว่ามี "ปุ่มประวัติการใช้งาน" (History Login) หรือไม่
            history_login = page.locator(".list-login").first
            
            # รอสักพักให้ปุ่มประวัติโหลด (ถ้ามี)
            try:
                history_login.wait_for(state='visible', timeout=5000)
            except:
                pass

            if history_login.is_visible():
                print(f"👤 [Login] พบประวัติการล็อกอินเดิม ({self.username}) กำลังคลิกเพื่อไปต่อ...")
                history_login.click(force=True)
                self.random_sleep(1, 2)
            else:
                # 3. ถ้าไม่มีประวัติ ให้กรอก Username แบบปกติ
                print("📝 [Login] ไม่พบประวัติเดิม กำลังกรอก Username ใหม่...")
                user_input = page.get_by_placeholder("เบอร์โทร / อีเมล / ชื่อผู้ใช้ (Username)")
                user_input.wait_for(state='visible', timeout=5000)
                user_input.fill(self.username)
                page.get_by_role("button", name="ดำเนินการต่อ").click()
                self.random_sleep(1, 2)

            # 4. ไม่ว่าจะเข้าด้วยวิธีไหน สุดท้ายต้องกรอก Password
            print("🔒 [Login] กำลังกรอกรหัสผ่าน...")
            pass_input = page.get_by_placeholder("ระบุรหัสผ่าน")
            pass_input.wait_for(state='visible', timeout=5000)
            pass_input.fill(self.password)
            
            # กดยืนยันเพื่อเข้าสู่ระบบ
            page.get_by_role("button", name="ดำเนินการต่อ").click()
            
            # 🌟 แก้ไข: ใช้ wait_for แทน is_visible ทันที
            print("⏳ [Login] กำลังรอหน้า Dashboard โหลด...")
            try:
                # รอให้ปุ่มบนหน้า dashboard ปรากฏ (ให้เวลาสูงสุด 15 วิ)
                page.wait_for_selector("#btn_dropdown_ownertype", state='visible', timeout=15000)
                context.storage_state(path=self.state_file)
                print("✅ [Login] สำเร็จและบันทึกเซสชันเรียบร้อย!")
            except:
                print("❌ [Login] ล้มเหลว อาจติด Captcha หรือโหลดหน้าเว็บไม่ทัน")
                return False # ควร return False เพื่อให้บอทหยุดทำงาน หรือลองใหม่ ดีกว่าปล่อยให้ไปกดค้นหาแบบพังๆ

        except Exception as e:
            print(f"❌ [Login Error] เกิดข้อผิดพลาด: {e}")

    def select_owner(self, page):
        print("🔍 Selecting 'Owner' filter...")
        for attempt in range(3):
            try:
                # 0. เช็คก่อนว่าเลือกไว้หรือยัง
                check_text = page.locator('#dropdown-ownertype').inner_text().strip()
                if "เจ้าของ" in check_text or check_text == "Owner":
                    print(f"✅ 'Owner' is already selected (Current: {check_text}).")
                    return

                # 1. กดเปิด Dropdown
                dropdown_btn = page.locator('#btn_dropdown_ownertype').first
                dropdown_btn.wait_for(state='visible', timeout=10000)
                dropdown_btn.scroll_into_view_if_needed()
                dropdown_btn.click(force=True)
                
                # 2. รอแอนิเมชั่นกางออก
                page.wait_for_timeout(1000) 
                
                # 3. จิ้มเลือก
                owner_option = page.locator('li.dropdown-ownertype-data[data-key="1"] a').first
                owner_option.wait_for(state='visible', timeout=5000)
                owner_option.click(force=True)
                
                # 4. รอเช็คผลลัพธ์ (เพิ่มเวลาเป็น 3 วิ เพื่อชัวร์)
                page.wait_for_timeout(2500)
                final_text = page.locator('#dropdown-ownertype').inner_text().strip()
                print(f"DEBUG: Button text after selection: '{final_text}'")
                
                if "เจ้าของ" in final_text or final_text == "Owner":
                    print(f"✅ Confirmed: 'Owner' selected (Attempt {attempt + 1}).")
                    return
                else:
                    # ถ้ายังไม่เปลี่ยนอีกลองใช้ JS ช่วยรันคำสั่งเดิมซ้ำ
                    print("⚠️ Text didn't update. Trying JS force click...")
                    page.evaluate("""
                        var el = document.querySelector('li.dropdown-ownertype-data[data-key="1"] a');
                        if (el) el.click();
                    """)
                    page.wait_for_timeout(2000)
                    final_text_js = page.locator('#dropdown-ownertype').inner_text().strip()
                    if "เจ้าของ" in final_text_js:
                        print(f"✅ Confirmed via JS Fallback: 'Owner' selected.")
                        return
                    raise Exception(f"Selection didn't update (Got: '{final_text_js}')")

            except Exception as e:
                print(f"⚠️ Attempt {attempt + 1} for Owner failed: {e}")
                self.random_sleep(1, 2)
        print("❌ Failed to select Owner after 3 attempts.")

    def select_property_type(self, page, p_type="คอนโด"):
        if not p_type or p_type == "ทั้งหมด":
            return
            
        print(f"🔍 Selecting Property Type: {p_type}...")
        
        for attempt in range(3):
            try:
                # 0. เช็คก่อนว่าถูกเลือกอยู่แล้วไหม
                check_text = page.locator('#dropdown-actiontype').inner_text().strip()
                if p_type in check_text:
                    print(f"✅ '{p_type}' already selected.")
                    return

                # 1. กดเปิด Dropdown
                dropdown_btn = page.locator('#btn_dropdown_actiontype, #btn_dropdown_propertytype').first
                dropdown_btn.wait_for(state='visible', timeout=10000)
                dropdown_btn.scroll_into_view_if_needed()
                dropdown_btn.click(force=True)
                
                # 2. รอแอนิเมชั่นกางออก
                page.wait_for_timeout(1000) 
                
                # 3. จิ้มเลือกแบบระบุเจาะจง
                type_option = page.locator(f"li.dropdown-actiontype-data a:has-text('{p_type}'), li.dropdown-propertytype-data a:has-text('{p_type}')").first
                type_option.wait_for(state='visible', timeout=5000)
                type_option.click(force=True)
                
                # 4. เช็คผลลัพธ์
                page.wait_for_timeout(2500)
                final_text = page.locator('#dropdown-actiontype').inner_text().strip()
                print(f"DEBUG: PropType button text after selection: '{final_text}'")
                
                if p_type in final_text:
                    print(f"✅ Confirmed: '{p_type}' selected (Attempt {attempt + 1}).")
                    return
                else:
                    # ลองใช้ JS Fallback อีกแรง
                    print("⚠️ PropType text didn't update. Trying JS click...")
                    page.evaluate(f"""
                        var items = document.querySelectorAll('li.dropdown-actiontype-data a, li.dropdown-propertytype-data a');
                        for (var i = 0; i < items.length; i++) {{
                            if (items[i].innerText.trim().includes('{p_type}')) {{
                                items[i].click();
                                break;
                            }}
                        }}
                    """)
                    page.wait_for_timeout(2000)
                    final_text_js = page.locator('#dropdown-actiontype').inner_text().strip()
                    if p_type in final_text_js:
                        print(f"✅ Confirmed via JS Fallback: '{p_type}' selected.")
                        return
                    raise Exception(f"Selection did not stick (Got: '{final_text_js}')")
                    
            except Exception as e:
                print(f"⚠️ Attempt {attempt + 1} for {p_type} failed: {e}")
                self.random_sleep(1, 2)
        
        print(f"❌ Failed to select {p_type} after 3 attempts.")

    def search_zone(self, page, zone_keyword="บางนา"):
        print(f"🔍 [Search] เริ่มกระบวนการค้นหา: {zone_keyword}")
        
        try:
            # 1. พยายามเปิดระฆัง/ช่องค้นหาหลักก่อน (ถ้ามีโฆษณาบังให้ปิดก่อน)
            self.close_banners(page)
            
            # คลิกกล่องค้นหาหลักเพื่อเปิด Modal/Popup (ย้ำๆ จนกว่าจะขึ้น)
            print("1️⃣ คลิกเปิดกล่องพิมพ์โซน...")
            popup_opened = False
            for attempt in range(5):
                try:
                    # บางครั้งต้องเลื่อนจอให้เห็นกล่องค้นหาชัดๆ ก่อนกด
                    search_box_trigger = page.locator('#box-input-search, #search_zone_input').first
                    search_box_trigger.scroll_into_view_if_needed()
                    
                    # ลองคลิกปกติก่อน ถ้าไม่ติดใช้ Force หรือ JS
                    search_box_trigger.click(timeout=5000)
                    self.random_sleep(1, 2)
                    
                    # เช็คว่ากล่องลิสต์โผล่มาหรือยัง
                    if page.locator("#div_zone_list").is_visible():
                        popup_opened = True
                        break
                    else:
                        # ถ้ายังไม่เปิด ลองวิธี JS
                        print(f"   [Attempt {attempt+1}] Popup ไม่ขึ้น ลองเปิดด้วย JS...")
                        page.evaluate("() => { const el = document.querySelector('#box-input-search') || document.querySelector('#search_zone_input'); if(el) el.click(); }")
                        self.random_sleep(1, 2)
                        if page.locator("#div_zone_list").is_visible():
                            popup_opened = True
                            break
                except:
                    pass
                print(f"   [Retry] พยายามเปิด Popup อีกครั้ง ({attempt+1}/5)...")
            
            # 2. รอให้กล่องรายการ #div_zone_list โหลดขึ้นมา
            print("2️⃣ กำลังกวาดหารายการโซนทั้งหมดจากใน Popup (#div_zone_list)...")
            page.wait_for_selector("#div_zone_list", state='visible', timeout=10000)
            self.random_sleep(1, 2)
            
            # 3. ใช้ JS เข้าไปวิ่งไล่หาทีละบรรทัดใน #div_zone_list (พร้อมไถหน้าจอถ้าหาไม่เจอ)
            # ลบช่องว่างออกเวลาเทียบเพื่อให้ match string แหว่งๆ หรือมี HTML แทรกได้
            clean_zone = zone_keyword.replace(" ", "").replace("'", "\\'")
            
            clicked_text = None
            for scroll_attempt in range(15): # เลื่อนหาลึกสุด 15 ครั้ง
                js_script = f"""() => {{
                    let lists = document.querySelectorAll('#div_zone_list .follow-list');
                    for (let item of lists) {{
                        let text = item.innerText || item.textContent || "";
                        // ลบเว้นวรรคและแท็ก HTML (Playwright get innerText มาให้แล้ว)
                        let cleanText = text.replace(/[\\s\\n\\r]+/g, '');
                        
                        if (cleanText.includes('{clean_zone}')) {{
                            item.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                            item.click();
                            return text.replace(/[\\n\\r]+/g, ' ').trim();
                        }}
                    }}
                    
                    // หากันจนตาแฉะแล้วไม่เจอ เลื่อนกล่อง #div_zone_list ลงเพื่อดึงข้อมูลใหม่
                    let box = document.getElementById('div_zone_list');
                    if(box) {{
                        box.scrollTop += 500; // ไถลงทีละ 500px
                    }}
                    return null;
                }}"""
                
                clicked_text = page.evaluate(js_script)
                
                if clicked_text:
                    print(f"✨ ค้นพบโซนและคลิกสำเร็จ: '{clicked_text}'")
                    break
                else:
                    self.random_sleep(1, 1.5) # รอข้อมูลหน้าไหมโหลดเสร็จหลังเลื่อนจอ
                    
            if not clicked_text:
                print(f"⚠️ ไถหาจนสุดแล้วไม่พบโซนที่ตรงกับ '{zone_keyword}' จะลองใช้วิธีพิมพ์ช่องค้นหาแทน...")
                # Fallback: ถ้าหาไม่เจอจริงๆ ค่อยคลิกพิมพ์ค้นหาเหมือนเดิม
                search_input = page.locator("#search_zone").first
                if search_input.is_visible():
                    search_input.click()
                    search_input.fill("")
                    search_input.press_sequentially(zone_keyword, delay=150)
                    self.random_sleep(3, 5)
                    try:
                        suggestion = page.locator(".search_zone_list_item, .zone_item_data, .search-item-zone").first
                        suggestion.wait_for(state='visible', timeout=5000)
                        suggestion.click(force=True)
                    except:
                        search_input.press("Enter")

            # 4. รอผลลัพธ์โหลด
            print("4️⃣ กำลังรีเฟรชหน้าผลลัพธ์...")
            self.random_sleep(6, 9) 
            
            return True
            
        except Exception as e:
            print(f"❌ [Search Error]: เกิดข้อผิดพลาดตอนค้นหา: {e}")
            try:
                page.screenshot(path="error_search_robust.png", full_page=True)
                print("📸 บันทึกภาพหน้าจอไว้ที่ 'error_search_robust.png' เพื่อเช็คว่าพังตอนไหน")
            except:
                pass
            return False
    def scrape_living_insider(self, target_url, property_type="คอนโด", zone="อ่อนนุช", is_manual=False):
        yielded_count = 0
        launch_args = {"headless": False if is_manual else not SHOW_BROWSER, "args": ["--no-sandbox", "--disable-setuid-sandbox"]}
        if self.use_proxy and self.proxy_server:
            launch_args["proxy"] = {"server": self.proxy_server, "username": self.proxy_username, "password": self.proxy_password}

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_args)
            context_args = {'viewport': {'width': 1920, 'height': 1080}}
            if os.path.exists(self.state_file): context_args['storage_state'] = self.state_file
            
            context = browser.new_context(**context_args)
            
            context.add_init_script("window.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.innerHTML='#modal-condition-istock,.modal-backdrop,.PopupAds{display:none!important;pointer-events:none!important;}';document.documentElement.appendChild(s);});")
            
            page = context.new_page()
            Stealth().apply_stealth_sync(page)
            
            if is_manual:
                print("\n" + "="*50)
                print("🛠️ MANUAL MODE ACTIVATED")
                print("="*50)
                page.goto('https://www.livinginsider.com/', wait_until='domcontentloaded')
                input("\n1️⃣ กรุณา Login และ Filter ข้อมูลให้เรียบร้อยบนหน้าต่างเบราว์เซอร์\n2️⃣ เมื่อได้หน้าผลลัพธ์ที่ต้องการแล้ว ให้กด Enter ที่นี่เพื่อเริ่มดึงข้อมูล...\n> ")
                print("\n🚀 เริ่มต้นดึงข้อมูลอัตโนมัติจากหน้าที่เปิดอยู่...")
            else:
                self.login(page, context)
                self.close_banners(page)
                
                try:
                    self.select_owner(page)
                    self.select_property_type(page, p_type=property_type)
                    if zone: 
                        self.search_zone(page, zone)
                except Exception as e:
                    print(f"⚠️ Filtering error: {e}")

            current_page = 1
            while yielded_count < MAX_ITEMS_PER_RUN:
                print(f"\n--- Page {current_page} (Total Collected: {yielded_count}) ---")
                
                # 🌟 แก้ไขจุดที่ 1: เปลี่ยนมารอดูกล่องประกาศแทนลิงก์เจาะจง เผื่อเว็บเปลี่ยน URL
                try: 
                    # เปลี่ยนมารอลิงก์ประกาศเลย แทนรอกล่องครอบ เพราะคลาสกล่องชอบโดนปรับ
                    page.wait_for_selector("a.istock_detail_url, a[href*='istockdetail'], a[href*='livingdetail']", state='attached', timeout=15000)
                    page.wait_for_timeout(2000) # เผื่อดึงข้อมูลแบบ AJAX ให้กล่องราคามันโหลดเสร็จก่อน
                except: 
                    print("⚠️ โหลดตารางประกาศไม่ทัน หรือไม่มีข้อมูลแล้ว (Timeout)")
                    break

                # 🌟 แก้ไขจุดที่ 2: ดึงข้อมูลโดยกวาดลิงก์ที่กว้างขึ้น (รองรับทั้ง /detail และ istockdetail)
                items = page.evaluate("""(skipKeywords) => { 
                    const links = Array.from(document.querySelectorAll("a.istock_detail_url, a[href*='/detail'], a[href*='istockdetail'], a[href*='livingdetail']")); 
                    return links.map(a => { 
                        let p = '0';
                        let parent = a.closest('.box-istock-item, .istock-item, .item-list, .istock-list, .istock_topic_border, .istock-lists, .item, [class*="item"]');
                        if(parent) {
                            let priceParts = [];
                            // กวาดทุกกล่องราคาในประกาศนั้น
                            let costBoxes = parent.querySelectorAll('.listing_cost, .box-price, .price-box');
                            costBoxes.forEach(box => {
                                let label = box.innerText.includes('เช่า') ? '[RENT]' : '[SALE]';
                                let priceText = box.innerText.replace(/[\\n\\s]/g, '');
                                priceParts.push(label + priceText);
                            });
                            // ถ้าหาแบบแยกกล่องไม่เจอ ให้กวาดเนื้อหาทั้งหมด
                            if(priceParts.length === 0) p = parent.innerText.replace(/[\\n\\s]/g, ' '); 
                            else p = priceParts.join(' | ');
                        }
                        return {url: a.href, price: p};
                    }).filter(item => !item.url.includes('javascript') && item.url.includes('http') && item.url.includes('livinginsider.com'));
                }""", SKIP_KEYWORDS)

                valid_urls = []
                seen_urls = set()
                # ใช้ MAX_PRICE_LIMITS จาก config, default เป็น 10 ล้านถ้าไม่รู้ประเภท
                limit = MAX_PRICE_LIMITS.get(property_type, 10000000)
                print(f"💰 [Price Guard] Property: '{property_type}' | Limit: {limit:,.0f}")
                
                for item in items:
                    url = item['url']
                    if url in seen_urls: continue
                    seen_urls.add(url)
                    
                    raw_price_data = str(item['price'])
                    try:
                        is_over_budget = False
                        
                        # แยกส่วน [SALE] ออกจาก [RENT] เพราะราคาขายต่างหากที่ต้องกรอง
                        # JS scraper แปะ label [SALE] / [RENT] ไว้ให้แล้ว
                        if '[SALE]' in raw_price_data or '[RENT]' in raw_price_data:
                            # มี label แบ่งชัดเจน -> เช็คเฉพาะส่วน SALE เท่านั้น
                            sale_section = ""
                            for part in raw_price_data.split(' | '):
                                if '[SALE]' in part:
                                    sale_section += part
                            check_str = sale_section if sale_section else ""
                        else:
                            # ไม่มี label (fallback innerText) -> เช็คทั้งก้อน
                            check_str = raw_price_data
                        
                        # ถ้าไม่มี SALE price เลย (ประกาศเช่าอย่างเดียว) -> ปล่อยผ่าน
                        if check_str:
                            clean_price_str = check_str.replace(',', '')
                            price_numbers = re.finditer(r'(\d+(?:\.\d+)?)\s*(ล้าน)?', clean_price_str)
                            
                            for match in price_numbers:
                                val = float(match.group(1))
                                unit = match.group(2) or ''
                                
                                if 'ล้าน' in unit:
                                    num = val * 1000000
                                elif val >= 100000:  # ตัวเลขโดดๆ >= 100,000 ถือว่าเป็นราคาบาท
                                    num = val
                                else:
                                    continue  # เลขเล็กๆ เช่น ตร.ม., ห้อง, ชั้น -> ข้ามไป
                                
                                if num > limit:
                                    print(f"🚫 [Initial Guard] ตัดทิ้ง: ราคาขาย {num:,.0f} เกินงบ {limit:,.0f} (raw: '{raw_price_data.strip()[:80]}')")
                                    is_over_budget = True
                                    break
                                
                        if is_over_budget: continue
                            
                        valid_urls.append(url)
                    except Exception as e:
                        print(f"⚠️ [Parse Error] อ่านราคาหน้าแรกล้มเหลว -> วิ่งต่อก่อน ({e})")
                        valid_urls.append(url)

                # ทำการ Unique URL เพื่อกันการขูดข้อมูลซ้ำ
                for url in list(set(valid_urls)):
                    if yielded_count >= MAX_ITEMS_PER_RUN: 
                        break
                        
                    # Early Deduplication: Check if already scraped to dodge ban and save time
                    listing_id = url.split('/')[-1].replace('.html', '')
                    if getattr(self, 'firestore', None) and self.firestore.is_listing_exists(listing_id):
                        print(f"⏭️ ข้ามการขูด (เคยบันทึกไว้แล้ว): {url}")
                        continue
                    
                    print(f"Scraping: {url}")
                    dp = context.new_page()
                    Stealth().apply_stealth_sync(dp)
                    try:
                        # 1. รอให้หน้าโหลดสมบูรณ์ขึ้นอีกนิด
                        dp.goto(url, wait_until='load', timeout=45000)
                        self.random_sleep(2, 3)
                        self.close_banners(dp)
                        
                        # 2. กดปุ่ม "แสดงรายละเอียดเพิ่มเติม" หรือ "ข้อมูลเพิ่มเติม..."
                        try:
                            dp.evaluate("""() => {
                                let btns = document.querySelectorAll('.box-open-text a, .btn-open-text, [onclick*="openModalMoreDetail"], .font_title_more, .font_title_more_mobile');
                                btns.forEach(b => { try { b.click(); } catch(e){} });
                                
                                let spans = Array.from(document.querySelectorAll('span, a'));
                                spans.forEach(s => {
                                    if(s.innerText && (s.innerText.includes('แสดงรายละเอียดเพิ่มเติม') || s.innerText.includes('ข้อมูลเพิ่มเติม...'))) {
                                        try { s.click(); } catch(e){}
                                    }
                                });
                            }""")
                            self.random_sleep(1, 1.5)
                        except:
                            pass

                        # 2.1 กดปุ่ม "แสดงเบอร์โทร" (ถ้ามี) เพื่อให้เบอร์มือถือตัวจริงโผล่ออกมา
                        # ใช้ JS คลิกให้หมดทุกตัวในหน้า ป้องกันปัญหา Element กั้น หรือ Visibility
                        try:
                            dp.evaluate("""() => {
                                let btns = document.querySelectorAll('.p-phone-contact, .btn-show-phone, [onclick*="show_phone"]');
                                btns.forEach(b => { try { b.click(); } catch(e){} });
                                
                                let links = Array.from(document.querySelectorAll('a'));
                                links.forEach(a => {
                                    if(a.innerText && a.innerText.includes('คลิกเพื่อดูเบอร์โทร')) {
                                        try { a.click(); } catch(e){}
                                    }
                                });
                            }""")
                            self.random_sleep(2, 3) # รอให้ network โหลดเบอร์มาแปะ
                        except:
                            pass

                        # 2.2 เช็กเบอร์โทรในเนื้อหาตีกรอบว่ามันโผล่มาหรือยัง
                        found_phone_in_text = False
                        try:
                            # ขอดึงข้อความชั่วคราวฉบับด่วนเพื่อเช็กเบอร์ที่เพิ่งโผล่ออกมา
                            temp_locator = dp.locator('#zone_detail_istock, .detail-istock, .box-detail-istock, #detail-contract-istock').first
                            if temp_locator.is_visible(timeout=2000):
                                temp_text = temp_locator.inner_text()
                                # หาเบอร์โทรที่ขึ้นต้น 06, 08, 09 (อาจมี - คั่น)
                                if re.search(r'0[689]\d{1}-?\d{3}-?\d{4}', temp_text):
                                    found_phone_in_text = True
                        except:
                            pass

                        # 2.3 ถ้าไม่เจอเบอร์ในเนื้อหา ให้ลองกดไอคอนโทรศัพท์ด้านข้าง
                        hidden_contacts = []
                        if not found_phone_in_text:
                            try:
                                side_phone_btn = dp.locator("a#seephone-detail-new-design, a.co-tel").first
                                if side_phone_btn.is_visible(timeout=2000):
                                    side_phone_btn.click(force=True)
                                    self.random_sleep(2.0, 3.0) # รอนานหน่อย เพราะเป็น Popup ที่ต้องโหลดจาก Server
                                    
                                    # ดูดเบอร์จาก Modal ยืนยัน
                                    phone_modal_val = dp.locator("#phone_number_modal_show, #href_phone_modal").first
                                    if phone_modal_val.is_visible(timeout=3000):
                                        phone_text = phone_modal_val.inner_text().strip()
                                        
                                        # 🛡️ [Fix] ถ้าเบอร์มี 9 หลักและขึ้นต้นด้วย 6, 8, 9 ให้เติม 0 ข้างหน้า
                                        if len(phone_text) == 9 and phone_text[0] in ['6', '8', '9']:
                                            phone_text = "0" + phone_text
                                            print(f"💡 Fixed phone number format: {phone_text}")
                                            
                                        hidden_contacts.append(f"เบอร์โทรศัพท์ (สกัดจากไอคอนด่วน): {phone_text}")
                                        
                                    # ปิด Modal พับเก็บ (ถ้ามีปุ่มปิด หรือกด Esc)
                                    dp.keyboard.press('Escape')
                                    self.random_sleep(0.5, 1)

                                # สกัด LINE ID จากไอคอน Line
                                side_line_btn = dp.locator("a.co-line").first
                                if side_line_btn.is_visible(timeout=2000):
                                    line_url = side_line_btn.get_attribute("data-url")
                                    if line_url:
                                        hidden_contacts.append(f"LINE ID (สกัดจากไอคอนด่วน): {line_url}")
                            except Exception as e:
                                pass

                        # รอให้ทุกอย่างนิ่งสนิทก่อนกวาดข้อความ
                        self.random_sleep(1.5, 2)
                        
                        # 3. ใช้ locator ดึงข้อความ "เฉพาะส่วนเนื้อหาประกาศ" (ป้องกันขยะจาก Header/Footer)
                        raw_text = ""
                        breadcrumb_info = {}
                        try:
                            # 3.0 ดึง Breadcrumbs เพื่อเอาประเภททรัพย์และโซน
                            breadcrumb_info = dp.evaluate("""() => {
                                let items = Array.from(document.querySelectorAll('.breadcrumb li, ol.breadcrumb li, .breadcrumb-list li'));
                                let texts = items.map(li => li.innerText.trim()).filter(t => t && t !== 'Living Insider' && t !== 'LivingInsider' && t !== 'หน้าแรก');
                                return {
                                    property_type: texts[0] || "",
                                    zone: texts[1] || ""
                                };
                            }""")

                            # 3.1 ดึงด้วย JavaScript เพื่อกวาดเฉพาะส่วนที่ต้องการจริงๆ เท่านั้นแบบเป็นชิ้นๆ
                            raw_text = dp.evaluate("""() => {
                                let parts = [];
                                
                                // 1. หัวข้อและชื่อโครงการ
                                let titles = document.querySelectorAll('.box-show-header-project, .box-show-title-detail, h1.show-title');
                                titles.forEach(el => { if(el.innerText && el.innerText.trim()) parts.push(el.innerText.trim()); });
                                
                                // 1.5 ราคา (ดึงมาไว้เป็นข้อมูลอ้างอิงเผื่อในรายละเอียดไม่มี)
                                let prices = document.querySelectorAll('.box_full_price, .show_price_topic');
                                prices.forEach(el => { if(el.innerText && el.innerText.trim()) parts.push('[ราคาที่สกัดจากระบบ]: ' + el.innerText.replace(/\\n/g, ' ').trim()); });
                                
                                // 2. ข้อมูลอสังหาฯ (ห้องนอน ชั้น ขนาด ฯลฯ)
                                let props = document.querySelectorAll('.detail-list-property, .detail_property_list_new, .box-detail-istock');
                                props.forEach(el => { if(el.innerText && el.innerText.trim()) parts.push(el.innerText.trim()); });
                                
                                // 3. รายละเอียดแบบเต็ม
                                let desc = document.querySelectorAll('#desc-text-nl, .new-detail-desc, #zone_detail_istock, .detail-istock, #detail-contract-istock');
                                desc.forEach(el => { if(el.innerText && el.innerText.trim()) parts.push(el.innerText.trim()); });
                                
                                return parts.join('\\n\\n');
                            }""")
                        except:
                            pass
                            
                        if not raw_text or len(raw_text.strip()) < 10:
                            # ถ้าหาไม่เจอจริงๆ ค่อยดึงจากกล่องที่กว้างขึ้นมาอีกหน่อย หลีกเลี่ยง body ถ้าเป็นไปได้
                            try:
                                fallback_locator = dp.locator('.container, .blog-detail, main').first
                                fallback_locator.wait_for(state='attached', timeout=5000)
                                raw_text = fallback_locator.inner_text()
                            except:
                                body_locator = dp.locator('body')
                                body_locator.wait_for(state='attached', timeout=5000)
                                raw_text = body_locator.inner_text()
                        
                        # นำเบอร์โทรและ LINE ที่สกัดได้แบบพิเศษ แปะทับต่อท้ายข้อความดิบไปเลย Gemini จะได้อ่านเจอชัวร์ๆ
                        if hidden_contacts:
                            raw_text += "\n\n=== ข้อมูลติดต่อเพิ่มเติม (Extracted from Hidden Elements) ===\n" + "\n".join(hidden_contacts)
                        
                        # ดูดชื่อเจ้าของจาก HTML #nameOwner label
                        owner_name = "-"
                        try:
                            # ใช้ evaluate วิ่งเข้า DOM โดยตรงกันปัญหา is_visible timeout ของ Playwright
                            owner_name = dp.evaluate('''() => {
                                let el = document.querySelector("label[onclick*='gotoReviewpage']") || document.querySelector("#nameOwner label") || document.querySelector("#nameOwner");
                                return el ? el.innerText.trim() : "-";
                            }''')
                            if owner_name.endswith('...'):
                                owner_name = owner_name[:-3].strip()
                        except:
                            pass
                        
                        # ======== เพิ่มส่วนดึงรูปภาพ ========
                        try:
                            # หาปุ่มหรือรูปใหญ่เพื่อให้ LightGallery (ถ้ามี) โหลดขึ้นมาระหว่างคลิก
                            dp.evaluate('''() => {
                                let cover = document.querySelector('.owl-item.active img, .image-istock, #img-cover');
                                if(cover) cover.click();
                            }''')
                            self.random_sleep(1, 2)
                            
                            image_urls = dp.evaluate('''() => {
                                let imgs = Array.from(document.querySelectorAll('.lg-thumb-item img, .lg-item img, .image-istock, img[src*="og_detail"], img[src*="upload/topic"]'));
                                let urls = imgs.map(img => img.src || img.getAttribute('data-src'));
                                
                                let validUrls = urls.filter(src => {
                                    if (!src) return false;
                                    if (!src.includes('http')) return false;
                                    let lowerSrc = src.toLowerCase();
                                    if (['avatar', 'icon', 'banner', 'logo'].some(v => lowerSrc.includes(v))) return false;
                                    return src.includes('livinginsider.com') && (src.includes('og_detail') || src.includes('upload/topic'));
                                });
                                return [...new Set(validUrls)].slice(0, 100); // ดึงรูปภาพสูงสุด 100 รูป
                            }''')
                            # ปิด Gallery ทิ้งหลังกวาดรูปเสร็จ
                            dp.keyboard.press('Escape')
                            self.random_sleep(0.5, 1)
                        except Exception as img_err:
                            print(f"⚠️ ดึงภาพไม่สำเร็จ: {img_err}")
                            image_urls = []
                        # =====================================

                        # ======== ดึงข้อมูล Project Details (built_year, floors, units ฯลฯ) ========
                        project_details = {}
                        try:
                            project_text = dp.evaluate('''() => {
                                let el = document.querySelector('.box-show-text-all-project');
                                return el ? el.innerText.replace(/[\\n\\r]+/g, ' ').trim() : "";
                            }''')
                            if project_text:
                                yr_m = re.search(r'สร้างเสร็จปี\s*(\d{4})', project_text)
                                if yr_m: project_details['built_year'] = int(yr_m.group(1))
                                
                                b_m = re.search(r'จำนวนอาคารในโครงการนี้มีทั้งหมด\s*(\d+)\s*อาคาร', project_text)
                                if b_m: project_details['scraped_num_buildings'] = int(b_m.group(1))
                                
                                f_m = re.search(r'มีความสูง\s*(\d+)\s*ชั้น', project_text)
                                if f_m: project_details['scraped_max_floors'] = int(f_m.group(1))
                                
                                u_m = re.search(r'มีจำนวนห้องพักอาศัยจำนวน\s*(\d+)\s*ยูนิต', project_text)
                                if u_m: project_details['scraped_total_units'] = int(u_m.group(1))
                                
                                addr_m = re.search(r'มีสถานที่ตั้งโครงการอยู่ที่\s+(.*?)(?=\s+จำนวนอาคาร|\s+สร้างเสร็จปี|$)', project_text)
                                if addr_m: project_details['scraped_address'] = addr_m.group(1).strip()
                                
                                name_m = re.search(r'ข้อมูลเกี่ยวกับโครงการ\s+(.*?)\s+มีสถานที่ตั้งโครงการอยู่ที่', project_text)
                                if name_m: project_details['scraped_project_name'] = name_m.group(1).strip()
                        except Exception as proj_err:
                            pass
                        # =====================================
                        
                        # 4. ส่งข้อมูลออกทันทีด้วย yield (ช่วยประหยัด RAM และเซฟได้ทันที)
                        if raw_text and len(raw_text.strip()) > 0:
                            yield {
                                "listing_id": url.split('/')[-1].replace('.html', ''), 
                                "url": url, 
                                "images": image_urls,
                                "owner_name": owner_name,
                                "property_type": breadcrumb_info.get('property_type', ''),
                                "zone": breadcrumb_info.get('zone', ''),
                                "extracted_phone": ", ".join(hidden_contacts) if hidden_contacts else "-",
                                "raw_text": raw_text[:5000],
                                **project_details
                            }
                            yielded_count += 1
                            print(f"✅ ขูดสำเร็จ (รายการที่ {yielded_count}/{MAX_ITEMS_PER_RUN}) - กำลังส่งไปวิเคราะห์...")
                        else:
                            print(f"⚠️ เนื้อหาว่างเปล่า ข้าม {url}")
                            
                    except Exception as e:
                        print(f"❌ [Scrape Error] ข้าม {url}: {str(e).split('===========================')[0].strip()}")
                    finally: 
                        try:
                            dp.close()
                        except:
                            pass
                        # เคลียร์แท็บเด้งทั้งหมด (Popup/New Tab) ที่อาจโผล่มา
                        for p_extra in context.pages:
                            if p_extra != page:
                                try: p_extra.close()
                                except: pass

                # Pagination
                next_btn = page.locator(f"ul.pagination li a:has-text('{current_page + 1}')").first
                if next_btn.is_visible():
                    next_btn.click(force=True)
                    current_page += 1
                    self.random_sleep(4, 6)
                else: break

            browser.close()
        # End of Generator