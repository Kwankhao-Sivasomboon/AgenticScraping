import os
import time
import random
import re
from datetime import datetime
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
                // var backdrops = document.querySelectorAll('.modal-backdrop');
                // backdrops.forEach(el => { el.style.setProperty('display', 'none', 'important'); });
                // document.body.classList.remove('modal-open');
                // document.body.style.overflow = 'auto';
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
        print(f"🔍 [Search] เริ่มกระบวนการค้นหา: {zone_keyword}")
        try:
            # 1. กดให้ pop up ขึ้นมา
            print("1️⃣ คลิกเปิด Popup...")
            # ยิง JavaScript เปิด Popup เพื่อความชัวร์ที่สุด เพราะกล่องเดิมอาจจะโดนทับ
            page.evaluate("let box = document.getElementById('box-input-search'); if(box) box.click();")
            self.random_sleep(1, 2)
            
            # 2. คลิกที่ช่องพิมพ์ใน Popup อีกที
            print("2️⃣ รอช่องพิมพ์ #search_zone")
            search_input = page.locator("#search_zone").first
            search_input.wait_for(state='visible', timeout=10000)
            search_input.click(force=True)
            search_input.fill("")

            # 3. พิมพ์ด้วย delay 150ms ตามที่คุณต้องการ
            print(f"3️⃣ เริ่มพิมพ์: {zone_keyword}")
            search_input.press_sequentially(zone_keyword, delay=150)

            # 4. หยุดรอให้เว็บดึง Autocomplete (สำคัญมาก)
            self.random_sleep(3, 4) 

            # 5. แล้ว Enter
            print("4️⃣ กด Enter!")
            search_input.press('Enter')

            # 6. รอให้ข้อมูลรีเฟรช
            self.random_sleep(6, 8) 
            
            return True
            
        except Exception as e:
            print(f"❌ [Search Error]: {e}")
            return False

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
                
                # 🌟 แก้ไขจุดที่ 1: เปลี่ยนมารอดูกล่องประกาศแทนลิงก์เจาะจง เผื่อเว็บเปลี่ยน URL
                try: 
                    # เปลี่ยนมารอลิงก์ประกาศเลย แทนรอกล่องครอบ เพราะคลาสกล่องชอบโดนปรับ
                    page.wait_for_selector("a.istock_detail_url, a[href*='istockdetail'], a[href*='livingdetail']", state='attached', timeout=15000)
                    page.wait_for_timeout(2000) # เผื่อดึงข้อมูลแบบ AJAX ให้กล่องราคามันโหลดเสร็จก่อน
                except: 
                    print("⚠️ โหลดตารางประกาศไม่ทัน หรือไม่มีข้อมูลแล้ว (Timeout)")
                    break

                # 🌟 แก้ไขจุดที่ 2: ดึงข้อมูลโดยกวาดลิงก์ที่กว้างขึ้น (รองรับทั้ง /detail และ istockdetail)
                items = page.evaluate("(skipKeywords) => { \
                    const links = Array.from(document.querySelectorAll(\"a.istock_detail_url, a[href*='/detail'], a[href*='istockdetail'], a[href*='livingdetail']\")); \
                    return links.map(a => { \
                        let p = '0'; \
                        let parent = a.closest('.box-istock-item, .istock-item, .item-list, .istock-list, .istock_topic_border, .istock-lists'); \
                        if(parent) { \
                            let priceEl = parent.querySelector('.text_price, .price, .font-price'); \
                            if(priceEl) p = priceEl.innerText || priceEl.textContent; \
                        } \
                        return {url: a.href, price: p}; \
                    }).filter(item => !item.url.includes('javascript') && item.url.includes('http')); \
                }", SKIP_KEYWORDS)

                valid_urls = []
                seen_urls = set()
                limit = MAX_PRICE_LIMITS.get(property_type, 999999999) 
                
                for item in items:
                    url = item['url']
                    
                    # กันลิงก์ซ้ำ (1 ประกาศอาจจะมีหลายลิงก์ ทำให้ล็อกและเช็คราคาซ้ำหลายรอบ)
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    
                    raw_price = str(item['price']).replace('฿', '').replace(',', '').strip()
                    
                    try:
                        p_val = 0
                        # แก้ปัญหาแปลงคำว่า "ล้าน" เป็นตัวเลข (กันบ้าน 11 ล้านหลุดมา)
                        if 'ล้าน' in raw_price:
                            clean_price = raw_price.replace('ล้าน', '').strip()
                            p_val = float(clean_price) * 1000000
                        else:
                            # ดึงเฉพาะตัวเลขและจุดทศนิยม
                            digits = ''.join(c for c in raw_price if c.isdigit() or c == '.')
                            if digits: p_val = float(digits)
                        
                        if p_val > limit:
                            print(f"🚫 ตัดทิ้ง: ราคา {p_val:,.0f} (เกินงบ {limit:,.0f})")
                            continue 
                            
                        valid_urls.append(url)
                    except Exception as e:
                        valid_urls.append(url)

                # ทำการ Unique URL เพื่อกันการขูดข้อมูลซ้ำ
                for url in list(set(valid_urls)):
                    if len(results) >= MAX_ITEMS_PER_RUN: 
                        break
                    
                    print(f"Scraping: {url}")
                    dp = context.new_page()
                    stealth_sync(dp)
                    try:
                        # 1. รอให้หน้าโหลดสมบูรณ์ขึ้นอีกนิด
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

                # Pagination
                next_btn = page.locator(f"ul.pagination li a:has-text('{current_page + 1}')").first
                if next_btn.is_visible():
                    next_btn.click(force=True)
                    current_page += 1
                    self.random_sleep(4, 6)
                else: break

            browser.close()
        return results