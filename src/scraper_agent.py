import os
import time
import random
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from config import MAX_ITEMS_PER_RUN, SKIP_KEYWORDS, MAX_PRICE_LIMITS

class ScraperAgent:
    def __init__(self):
        self.use_proxy = os.getenv('USE_PROXY', 'false').lower() == 'true'
        self.proxy_server = os.getenv('PROXY_SERVER')
        self.proxy_username = os.getenv('PROXY_USERNAME')
        self.proxy_password = os.getenv('PROXY_PASSWORD')
        self.username = os.getenv('LIVING_INSIDER_USERNAME')
        self.password = os.getenv('LIVING_INSIDER_PASSWORD')
        self.state_file = "playwright_state.json"

    def random_sleep(self, min_seconds=2, max_seconds=5):
        time.sleep(random.uniform(min_seconds, max_seconds))

    def close_banners(self, page):
        """จัดการ Popup และ Ad ด้วย JS เพื่อความรวดเร็วและไม่ขวางทางบอท"""
        try:
            page.evaluate("""
                var closeBtns = document.querySelectorAll('.btn-close, .close, #popup-close, [onclick*="closeBanner"]');
                closeBtns.forEach(btn => { try { btn.click(); } catch(e) {} });
                var backdrops = document.querySelectorAll('.modal-backdrop');
                backdrops.forEach(el => { el.style.setProperty('display', 'none', 'important'); });
                document.body.classList.remove('modal-open');
                document.body.style.overflow = 'auto';
            """)
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
            self.random_sleep(5, 7)
            
            # ตรวจสอบว่ากลับมาหน้า Dashboard หรือยัง
            if "member_istock" not in page.url:
                page.goto('https://www.livinginsider.com/member_istock.php', wait_until='domcontentloaded')
                self.random_sleep(3, 5)

            if page.locator("#btn_dropdown_ownertype").is_visible():
                context.storage_state(path=self.state_file)
                print("✅ [Login] สำเร็จและบันทึกเซสชันเรียบร้อย!")
            else:
                print("❌ [Login] ล้มเหลว อาจติด Captcha หรือรหัสผ่านผิด")

        except Exception as e:
            print(f"❌ [Login Error] เกิดข้อผิดพลาด: {e}")

    def select_owner(self, page):
        print("🔍 Selecting 'Owner' filter...")
        try:
            dropdown_btn = page.locator('#btn_dropdown_ownertype')
            dropdown_btn.wait_for(state='visible', timeout=10000)
            dropdown_btn.click(force=True)
            self.random_sleep(1.5, 2.5) 
            
            owner_option = page.locator('li.dropdown-ownertype-data[data-key="1"] a').first
            owner_option.wait_for(state='visible', timeout=5000)
            owner_option.hover()
            self.random_sleep(0.5, 1)
            owner_option.click(force=True)
            
            print("✅ Clicked 'Owner' successfully.")
            self.random_sleep(2, 3)
        except Exception as e:
            print(f"⚠️ Native click for Owner failed: {e}. Trying JavaScript Fallback...")
            try:
                page.evaluate("""
                    var ownerBtn = document.querySelector('li.dropdown-ownertype-data[data-key="1"] a');
                    if (ownerBtn) { ownerBtn.click(); }
                """)
                self.random_sleep(2, 3)
            except Exception as js_e:
                print(f"❌ Selection failed completely: {js_e}")

    def select_property_type(self, page, p_type="คอนโด"):
        if not p_type or p_type == "ทั้งหมด":
            return
            
        print(f"🔍 Selecting Property Type: {p_type}...")
        try:
            dropdown_btn = page.locator('#btn_dropdown_actiontype')
            dropdown_btn.wait_for(state='visible', timeout=10000)
            dropdown_btn.click(force=True)
            self.random_sleep(1.5, 2.5) 
            
            type_option = page.locator(f"li.dropdown-actiontype-data a:has-text('{p_type}')").first
            type_option.wait_for(state='visible', timeout=5000)
            type_option.hover()
            self.random_sleep(0.5, 1)
            type_option.click(force=True)
            
            print(f"✅ Selected '{p_type}' successfully.")
            self.random_sleep(2, 3)
        except Exception as e:
            print(f"⚠️ Native click for {p_type} failed. Trying JavaScript Fallback...")
            try:
                page.evaluate(f"""
                    var items = document.querySelectorAll('li.dropdown-actiontype-data a');
                    for (var i = 0; i < items.length; i++) {{
                        if (items[i].innerText.includes('{p_type}')) {{
                            items[i].click();
                            break;
                        }}
                    }}
                """)
                self.random_sleep(2, 3)
            except Exception as js_e:
                print(f"❌ Selection failed completely: {js_e}")

    def search_zone(self, page, zone_keyword="บางนา"):
        """เน้นการ 'บังคับ' เปิดหน้าต่างค้นหา และคลิกเลือกจากรายการที่เว็บแนะนำ"""
        print(f"🔍 [Search] กำลังพยายามเปิดช่องค้นหาสำหรับ: {zone_keyword}")
        try:
            # 1. คลิกกล่องค้นหาหลัก (ลองทั้งวิธีปกติ และวิธีส่ง Event คลิกโดยตรง)
            trigger_box = page.locator("#box-input-search").first
            trigger_box.wait_for(state='visible', timeout=10000)
            
            # ย้ำ 2 รอบเพื่อให้หน้าต่างเปิดแน่นอน
            trigger_box.click(force=True)
            self.random_sleep(0.5, 1)
            
            # 2. ตรวจเช็คว่าช่องพิมพ์โผล่มาหรือยัง
            search_input = page.locator("#search_zone").first
            if not search_input.is_visible():
                print("⚠️  หน้าต่างไม่เด้ง กำลังใช้แผนสำรองคลิกที่ตัวอักษร 'ค้นหา'...")
                page.locator(".placeholder-box").first.click(force=True)
            
            search_input.wait_for(state='visible', timeout=5000)
            print("✅ [Search] ช่องพิมพ์ปรากฏแล้ว")

            # 3. คลิกล้างค่าและเริ่มพิมพ์แบบทีละตัว
            search_input.click(force=True)
            search_input.fill("")
            search_input.press_sequentially(zone_keyword, delay=150)
            
            # *** จุดชี้เป็นชี้ตาย: ต้องรอให้ Autocomplete เด้งขึ้นมา ***
            print(f"⏳ [Search] รอรายการแนะนำสำหรับ '{zone_keyword}'...")
            self.random_sleep(3, 4) 

            # 4. บังคับคลิกที่ตัวเลือกแรกที่เว็บแนะนำ (LivingInsider บังคับให้เลือกจากลิสต์)
            try:
                # มองหาแถบรายการแนะนำที่เด้งขึ้นมาใต้ช่องพิมพ์
                suggestion = page.locator(".tt-suggestion, .autocomplete-suggestion").first
                if suggestion.is_visible(timeout=3000):
                    print("🎯 [Search] พบรายการแนะนำ กำลังคลิกเลือก...")
                    suggestion.click(force=True)
                    self.random_sleep(1, 2)
            except:
                print("⚠️  ไม่พบรายการแนะนำ จะลองกด Enter ตรงๆ")

            # 5. ส่งคำสั่ง Enter เพื่อเริ่มค้นหาข้อมูลใหม่
            print("⌨️  [Search] กำลังส่งคำสั่ง Enter...")
            search_input.press('Enter')

            # 6. รอให้ข้อมูลรีเฟรช (สำคัญมาก กันบอทรีบวิ่งไปดึงข้อมูลหน้าเก่า)
            print("⏳ [Search] รอข้อมูลใหม่โหลดสักครู่...")
            self.random_sleep(6, 8) 
            
            return True
            
        except Exception as e:
            print(f"❌ [Search Error] ทำงานไม่ครบขั้นตอน: {e}")
            return True

    def scrape_living_insider(self, target_url, property_type="คอนโด", zone="อ่อนนุช"):
        results = []
        launch_args = {"headless": False, "args": ["--no-sandbox", "--disable-setuid-sandbox"]}
        if self.use_proxy and self.proxy_server:
            launch_args["proxy"] = {"server": self.proxy_server, "username": self.proxy_username, "password": self.proxy_password}

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_args)
            context_args = {'viewport': {'width': 1920, 'height': 1080}}
            if os.path.exists(self.state_file): context_args['storage_state'] = self.state_file
            
            context = browser.new_context(**context_args)
            
            context.add_init_script("window.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.innerHTML='#modal-condition-istock,.modal-backdrop,.PopupAds{display:none!important;pointer-events:none!important;}';document.documentElement.appendChild(s);});")
            
            page = context.new_page()
            stealth_sync(page)
            
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
            while len(results) < MAX_ITEMS_PER_RUN:
                print(f"\n--- Page {current_page} (Total: {len(results)}) ---")
                try: page.wait_for_selector("a[href*='istockdetail/']", timeout=10000)
                except: break

                items = page.evaluate("(skipKeywords) => { \
                    return Array.from(document.querySelectorAll(\"a[href*='istockdetail/']\")).map(a => { \
                        let p = a.closest('.box-istock-item')?.querySelector('.text_price')?.innerText || '0'; \
                        return {url: a.href, price: p}; \
                    }); \
                }", SKIP_KEYWORDS)

                valid_urls = []
                limit = MAX_PRICE_LIMITS.get(property_type, 999999999) 
                
                for item in items:
                    url = item['url']
                    raw_price = str(item['price']).replace('฿', '').replace(',', '').strip()
                    
                    try:
                        p_val = 0
                        # แก้ปัญหาแปลงคำว่า "ล้าน" เป็นตัวเลข (กันบ้าน 11 ล้านหลุดมา)
                        if 'ล้าน' in raw_price:
                            clean_price = raw_price.replace('ล้าน', '').strip()
                            p_val = float(clean_price) * 1000000
                        else:
                            p_val = float(''.join(c for c in raw_price if c.isdigit() or c == '.'))
                        
                        if p_val > limit:
                            print(f"🚫 ตัดทิ้ง: ราคา {p_val:,.0f} (เกินงบ {limit:,.0f})")
                            continue 
                            
                        valid_urls.append(url)
                    except Exception as e:
                        valid_urls.append(url)

                for url in list(set(valid_urls)):
                    if len(results) >= MAX_ITEMS_PER_RUN: 
                        break
                    
                    print(f"Scraping: {url}")
                    dp = context.new_page()
                    stealth_sync(dp)
                    try:
                        # 1. รอให้หน้าโหลดสมบูรณ์ขึ้นอีกนิด (เปลี่ยนจาก domcontentloaded เป็นการรอให้เครือข่ายนิ่ง)
                        dp.goto(url, wait_until='load', timeout=45000)
                        self.random_sleep(2, 3)
                        self.close_banners(dp)
                        
                        # 2. ใช้ locator ดึงข้อความแทน evaluate ป้องกัน context destroy
                        body_locator = dp.locator('body')
                        body_locator.wait_for(state='attached', timeout=10000)
                        raw_text = body_locator.inner_text()
                        
                        # 3. เซฟลง results เฉพาะกรณีที่ดึง raw_text ได้จริง
                        if raw_text and len(raw_text.strip()) > 0:
                            results.append({
                                "listing_id": url.split('/')[-1].replace('.html', ''), 
                                "url": url, 
                                "raw_text": raw_text[:5000]
                            })
                            print(f"✅ บันทึกสำเร็จ (Total: {len(results)}/{MAX_ITEMS_PER_RUN})")
                        else:
                            print(f"⚠️ เนื้อหาว่างเปล่า ข้าม {url}")
                            
                    except Exception as e:
                        print(f"❌ [Scrape Error] ข้าม {url}: {str(e).split('===========================')[0].strip()}")
                    finally: 
                        dp.close()

                next_btn = page.locator(f"ul.pagination li a:has-text('{current_page + 1}')").first
                if next_btn.is_visible():
                    next_btn.click(force=True)
                    current_page += 1
                    self.random_sleep(4, 6)
                else: break

            browser.close()
        return results