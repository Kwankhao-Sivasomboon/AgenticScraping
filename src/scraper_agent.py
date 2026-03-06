import os
import time
import random
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

class ScraperAgent:
    def __init__(self):
        # 1. Setup Proxy variables
        self.use_proxy = os.getenv('USE_PROXY', 'false').lower() == 'true'
        self.proxy_server = os.getenv('PROXY_SERVER')
        self.proxy_username = os.getenv('PROXY_USERNAME')
        self.proxy_password = os.getenv('PROXY_PASSWORD')
        
        # 2. Session State file
        self.state_file = "playwright_state.json"

    def random_sleep(self, min_seconds=2, max_seconds=5):
        """Human-like Behavior: Add random delay to prevent rate limiting"""
        sleep_time = random.uniform(min_seconds, max_seconds)
        print(f"Waiting for {sleep_time:.2f} seconds...")
        time.sleep(sleep_time)

    def close_banners(self, page):
        """Close any annoying promotional banners blocking the screen."""
        print("Checking for blocking banners (allowing time for late ads to load)...")
        for _ in range(2):
            try:
                # Explicitly target the condition modal from the user's codegen
                try:
                    if page.locator("#modal-condition-istock").is_visible(timeout=500):
                        page.locator("#modal-condition-istock").get_by_label("Close").click(force=True)
                except:
                    pass

                # Safely click just the ad close buttons
                page.evaluate("""
                    var closeBtns = document.querySelectorAll('.btn-close[data-dismiss="modal"], .btn-close[onclick*="closeBanner"], a[onclick*="closeBannerAcceptAgent"], a.btn-close[onclick="closeBannerAcceptAgent();"], .close[data-dismiss="modal"], button.close[data-dismiss="modal"], #popup-close');
                    closeBtns.forEach(btn => {
                        try { btn.click(); } catch(e) {}
                    });
                    
                    // Force hide backdrops specifically
                    var backdrops = document.querySelectorAll('.modal-backdrop');
                    backdrops.forEach(el => {
                        el.style.setProperty('display', 'none', 'important');
                        el.style.setProperty('pointer-events', 'none', 'important');
                    });
                    
                    document.body.classList.remove('modal-open');
                    document.body.style.setProperty('overflow', 'auto', 'important');
                """)
                self.random_sleep(1, 2)  # Wait and let other ads pop up if any
            except Exception as e:
                pass

    def login(self, page, context):
        """Perform login and save session state."""
        print("Checking login status...")
        
        username = os.getenv('LIVING_INSIDER_USERNAME')
        password = os.getenv('LIVING_INSIDER_PASSWORD')
        
        if not username or not password:
            print("Warning: Login credentials not found. Proceeding as guest.")
            return

        # Go directly to member_istock.php. If not logged in, it will show the login prompt.
        page.goto('https://www.livinginsider.com/member_istock.php', wait_until='domcontentloaded', timeout=60000)
        self.random_sleep(2, 4)
        
        # Determine if we are on dashboard or login page
        try:
            # Check if we are already logged in
            if page.locator("#btn_dropdown_ownertype").is_visible(timeout=3000) or page.locator("a[href*='logout']").is_visible(timeout=1000):
                print("Session active! No need to login again.")
                return
        except Exception as e:
            pass

        print("Session expired or not found. Performing login...")
        try:
            # Check which type of login form loaded using short timeouts
            try:
                username_input = page.get_by_placeholder("เบอร์โทร / อีเมล / ชื่อผู้ใช้ (Username)")
                if username_input.is_visible(timeout=3000):
                    username_input.fill(username)
                    page.get_by_role("button", name="ดำเนินการต่อ").click()
                    self.random_sleep(1, 3)
                    
                    page.get_by_placeholder("ระบุรหัสผ่าน").fill(password)
                    page.get_by_role("button", name="ดำเนินการต่อ").click()
                    print("Logged in using Codegen Method.")
            except:
                try:
                    if page.locator(".list-login").is_visible(timeout=2000):
                        page.locator('.list-login').first.click(force=True)
                        self.random_sleep(1, 2)
                        page.get_by_placeholder("ระบุรหัสผ่าน").fill(password)
                        page.get_by_role("button", name="ดำเนินการต่อ").click()
                        print("Logged in using List-Login Method.")
                    elif page.locator(".email-login").is_visible(timeout=1000):
                        page.locator('.email-login').first.click(force=True)
                        self.random_sleep(1, 2)
                        page.get_by_placeholder("ระบุรหัสผ่าน").fill(password)
                        page.get_by_role("button", name="ดำเนินการต่อ").click()
                        print("Logged in using Email-Login Method.")
                except:
                    # Fallback to old input selectors with explicit short timeouts
                    page.locator('#login_username').fill(username, timeout=3000)
                    page.locator('button.btn-next-step[data-step="1"]').click(timeout=3000)
                    self.random_sleep(1, 2)
                    page.locator('#password').fill(password, timeout=3000)
                    page.locator('button.btn-next-step[data-step="2"]').click(timeout=3000)
                    print("Logged in using Legacy Method.")

            self.random_sleep(3, 5)
            # Guarantee we land back on dashboard after login
            if "member_istock" not in page.url:
                print("Navigating back to member istock area...")
                page.goto('https://www.livinginsider.com/member_istock.php', wait_until='domcontentloaded', timeout=60000)
                self.random_sleep(3, 5)

            # SAVE SESSION!
            context.storage_state(path=self.state_file)
            print("Session state saved! Next run will use this session.")
        except Exception as e:
            print(f"Login failed: {e}")

    def select_owner(self, page):
        """Filter by 'Owner' from the dropdown."""
        print("Selecting 'Owner' filter...")
        try:
            # Wait for the button to appear in the DOM
            page.wait_for_selector('#btn_dropdown_ownertype', state='attached', timeout=10000)
            
            # Bypass Playwright's interactability checks completely using native JS click
            page.evaluate("""
                var btn = document.getElementById('btn_dropdown_ownertype');
                if (btn) btn.click();
            """)
            self.random_sleep(0.5, 1)
            
            # Click the exact owner type option using its HTML data attribute
            page.evaluate("""
                var option = document.querySelector('li.dropdown-ownertype-data[data-key="1"] a');
                if (option) option.click();
            """)
            self.random_sleep(1, 2) 
        except Exception as e:
            print(f"Error selecting owner filter: {e}")

    def select_property_type(self, page, p_type="คอนโด"):
        """Filter by Property Type e.g., 'คอนโด', 'บ้าน'"""
        print(f"Selecting Property Type: {p_type}...")
        try:
            # Wait for the button to appear in the DOM
            page.wait_for_selector('#btn_dropdown_actiontype', state='attached', timeout=10000)
            
            # Step 1: Open Dropdown
            page.evaluate("""
                var btn = document.getElementById('btn_dropdown_actiontype');
                if (btn) btn.click();
            """)
            self.random_sleep(0.5, 1)
            
            # Step 2: Select the Type using JS iteration
            js_code = f"""
                var items = document.querySelectorAll('li.dropdown-actiontype-data a');
                for (var i = 0; i < items.length; i++) {{
                    if (items[i].innerText.includes('{p_type}')) {{
                        items[i].click();
                        break;
                    }}
                }}
            """
            page.evaluate(js_code)
                
            self.random_sleep(1, 2)
        except Exception as e:
            print(f"Error selecting property type: {e}")

    def search_zone(self, page, zone_keyword="อ่อนนุช"):
        """Search and select a specific zone/location."""
        print(f"Searching for zone: {zone_keyword}...")
        try:
            # 1. Open the search input modal
            try:
                page.get_by_text("ค้นหา..").click(timeout=3000)
            except:
                page.evaluate("var b = document.getElementById('box-input-search'); if(b) b.click();")
                
            self.random_sleep(1, 1.5)
            
            # 2. Type into the specific input to trigger AJAX suggestions
            try:
                page.get_by_role("textbox", name="ค้นหาทำเล").click(timeout=3000)
                page.get_by_role("textbox", name="ค้นหาทำเล").fill(zone_keyword)
            except:
                # Clear using native ID method fallback
                page.locator('#search_zone').fill('')
                page.locator('#search_zone').press_sequentially(zone_keyword, delay=150)
                
            self.random_sleep(0.5, 1) # Wait just a bit before hitting enter
            
            try:
                page.get_by_role("textbox", name="ค้นหาทำเล").press('Enter')
            except:
                page.keyboard.press('Enter')
                
            print("Pressed Enter for search_zone")

            self.random_sleep(3, 6) # Wait for the board to refresh
            
            try:
                # Check if it shows "ไม่พบข้อมูล" (No data found)
                no_data = page.locator("div.text-danger:has-text('ไม่พบข้อมูล')")
                if no_data.count() > 0 and no_data.first.is_visible():
                    print("Found 'ไม่พบข้อมูล' message! No listing exists for this selection.")
                    return False
            except:
                pass
            
            return True
        except Exception as e:
            print(f"Error searching zone: {e}")
            return True

    def scrape_living_insider(self, target_url, property_type="คอนโด", zone=None):
        results = []
        
        # Cloud setup requires headless and no-sandbox
        launch_args = {
            "headless": False, # Changed to False for Local GUI Debugging
            "args": ["--no-sandbox", "--disable-setuid-sandbox"]
        }
        
        if self.use_proxy and self.proxy_server:
            print("Using Residential Proxy...")
            proxy_config = {"server": self.proxy_server}
            if self.proxy_username:
                proxy_config["username"] = self.proxy_username
                proxy_config["password"] = self.proxy_password
            launch_args["proxy"] = proxy_config

        print("Starting Scraper Agent...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_args)
            
            context_args = {
                'viewport': {'width': 1920, 'height': 1080},
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            # 3. Load Session State if exists!
            if os.path.exists(self.state_file):
                print("Found saved session, applying to browser...")
                context_args['storage_state'] = self.state_file
            
            context = browser.new_context(**context_args)
            
            # --- CSS-Level Ad Blocker (Block from start) ---
            # This injects a stylesheet instantly, forcing ads/backdrops to be hidden forever
            context.add_init_script("""
                window.addEventListener('DOMContentLoaded', () => {
                    const style = document.createElement('style');
                    style.innerHTML = `
                        #modal-condition-istock, 
                        #myModalIntro, 
                        #ads-banner, 
                        .PopupAds, 
                        .modal-backdrop {
                            display: none !important;
                            visibility: hidden !important;
                            pointer-events: none !important;
                            z-index: -9999 !important;
                            opacity: 0 !important;
                        }
                        body, html {
                            overflow: auto !important;
                            padding-right: 0 !important;
                        }
                    `;
                    document.documentElement.appendChild(style);
                });
            """)
            
            # --- Network-Level Ad Blocker ---
            ad_domains = [
                "doubleclick.net", "googlesyndication.com", "googleadservices.com", 
                "facebook.net", "facebook.com/tr", "google-analytics.com", 
                "googletagmanager.com", "criteo.com", "taboola.com", "outbrain.com",
                "ads-twitter.com", "hotjar.com", "adsco.re"
            ]
            
            def block_ads(route):
                if any(ad in route.request.url for ad in ad_domains):
                    route.abort()
                else:
                    route.continue_()
                    
            try:
                context.route("**/*", block_ads)
                print("Network-level ad blocker activated.")
            except Exception as e:
                print(f"Could not setup network ad blocker: {e}")
            # --------------------------------
            
            page = context.new_page()
            stealth_sync(page)
            
            # Execute Login (will skip if session is valid)
            self.login(page, context)
            
            self.close_banners(page)

            self.select_owner(page)
            self.select_property_type(page, p_type=property_type)
            
            if zone:
                success = self.search_zone(page, zone_keyword=zone)
                if not success:
                    print(f"Skipping scrape because no listings were found for type '{property_type}' in '{zone}'.")
                    browser.close()
                    return None

            print("Extracting istock detailing URLs (Skipping properties marked with 'ดัน')...")
            try:
                page.wait_for_selector("a[href*='istockdetail/']", timeout=10000)
                
                # Fetch valid links that don't have "ดัน" in their date box to avoid wasting time on bumped listings
                js_script = """
                () => {
                    const links = new Set();
                    document.querySelectorAll("a[href*='istockdetail/']").forEach(a => {
                        let container = a;
                        let foundDate = false;
                        for (let i=0; i<8; i++) {
                            if (!container) break;
                            let dateElem = container.querySelector('.istock-lastdate');
                            if (dateElem) {
                                foundDate = true;
                                let dateText = dateElem.innerText || "";
                                if (!dateText.includes('ดัน')) {
                                    links.add(a.href);
                                }
                                break;
                            }
                            container = container.parentElement;
                        }
                        // If we couldn't find the date label in parents, we add it just to be safe
                        if (!foundDate) {
                            links.add(a.href);
                        }
                    });
                    return Array.from(links);
                }
                """
                
                valid_urls = page.evaluate(js_script)
                
                unique_urls = set()
                for url in valid_urls:
                    if not url.startswith('http'):
                        url = f"https://www.livinginsider.com{url}"
                    unique_urls.add(url)
                
                url_list = list(unique_urls)
                
                for index, url in enumerate(url_list):
                    if index >= 3: # Limit for testing, you can remove this later
                        break
                        
                    print(f"\nProcessing Detail URL {index + 1}: {url}")
                    listing_id = url.split('/')[-1].replace('.html', '')
                    
                    # 4. Navigate into Detail Page!
                    detail_page = context.new_page()
                    stealth_sync(detail_page)
                    detail_page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    self.random_sleep(2, 4)
                    
                    self.close_banners(detail_page)
                    
                    # --- Contact Info Extraction from Icons ---
                    contact_icon_text = []
                    try:
                        # Click phone icon if found
                        tel_icon = detail_page.locator('img[src*="icon_tel_n.svg"], img[alt="tel"]').first
                        if tel_icon.is_visible():
                            tel_icon.click(timeout=3000)
                            detail_page.wait_for_selector('#phone_number_modal_show', timeout=3000)
                            phone_num = detail_page.locator('#phone_number_modal_show').first.inner_text()
                            if phone_num:
                                contact_icon_text.append(f"Phone_Icon: {phone_num}")
                            detail_page.keyboard.press('Escape') # Close popup
                            self.random_sleep(0.5, 1)
                    except:
                        pass
                        
                    try:
                        # Check for LINE icon and extract the full href link
                        line_icon = detail_page.locator('img[src*="icon-line-new-design.svg"], img[alt="line"]').first
                        if line_icon.is_visible():
                            parent_a = line_icon.locator('xpath=./parent::a')
                            line_link = "Available"
                            if parent_a.count() > 0:
                                href = parent_a.get_attribute('href')
                                if href:
                                    line_link = href
                            contact_icon_text.append(f"Line_URL: {line_link}")
                    except Exception as e:
                        pass
                        
                    contact_icon_str = ", ".join(contact_icon_text) if contact_icon_text else "None"
                    # ----------------------------------------
                    
                    # Reveal phone number in text if exists
                    try:
                        # 1. Expand "Show more details" to reveal hidden text (like Line ID)
                        try:
                            detail_page.get_by_role("link", name="แสดงรายละเอียดเพิ่มเติม").click(timeout=1500)
                        except:
                            pass
                            
                        try:
                            expand_btns = detail_page.locator('.btn-open-text')
                            for i in range(expand_btns.count()):
                                if expand_btns.nth(i).is_visible():
                                    expand_btns.nth(i).click(force=True)
                                    self.random_sleep(0.5, 1)
                        except Exception as e:
                            print(f"Error expanding details: {e}")
                            
                        # 2. Reveal all phone numbers inline using JS to guarantee unmasking
                        try:
                            detail_page.evaluate("""
                                var phoneBtns = document.querySelectorAll('.p-phone-contact, a[data-vouvist]');
                                phoneBtns.forEach(btn => { try { btn.click(); } catch(e) {} });
                            """)
                            self.random_sleep(0.5, 1.5)
                        except Exception as e:
                            print(f"Error revealing phone numbers: {e}")
                            
                        # 3. Reveal all emails
                        try:
                            email_btns = detail_page.locator('.p-email-contact')
                            for i in range(email_btns.count()):
                                if email_btns.nth(i).is_visible():
                                    email_btns.nth(i).click(force=True)
                                    self.random_sleep(0.5, 1)
                        except Exception as e:
                            print(f"Error revealing emails: {e}")
                            
                    except Exception as e:
                        pass
                    
                    self.random_sleep(1, 2) # Wait for DOM updates to render text
                    
                    # Extract raw text
                    raw_text = detail_page.evaluate("document.body.innerText")
                    # --- Extract All Images ---
                    image_urls = []
                    try:
                        # Check if "Show all pictures" button exists
                        more_pic_btn = detail_page.locator('.more_data_detail .box_relative, .icon_more_data').first
                        if more_pic_btn.is_visible():
                            print("Found 'Show all pictures' button, clicking to load gallery...")
                            more_pic_btn.click(force=True)
                            detail_page.wait_for_selector('.lg-thumb-item img', timeout=5000)
                            self.random_sleep(1, 2)
                            
                            # Extract all thumbnails from the gallery modal
                            gallery_imgs = detail_page.locator('.lg-thumb-item img')
                            for i in range(gallery_imgs.count()):
                                src = gallery_imgs.nth(i).get_attribute('src')
                                # Filter only property images, rejecting avatars/banners/icons
                                if src and 'http' in src and 'upload/topic' in src:
                                    image_urls.append(src)
                                    
                            # Close the gallery modal with Escape or close button
                            detail_page.keyboard.press('Escape')
                            self.random_sleep(0.5, 1)
                    except Exception as e:
                        print("Gallery not found or failed, falling back to standard extraction.")

                    # Fallback or additional standard extraction if gallery wasn't clicked
                    if not image_urls:
                        images = detail_page.query_selector_all('img')
                        for img in images:
                            src = img.get_attribute('src')
                            # Strict filter for property images only
                            if src and 'http' in src and 'upload/topic' in src:
                                image_urls.append(src)
                                
                    # Remove duplicates while preserving order
                    image_urls = list(dict.fromkeys(image_urls))
                    
                    detail_page.close()
                    
                    results.append({
                        "listing_id": listing_id,
                        "url": url,
                        "images": image_urls[:10], # Keep up to 10 images
                        "raw_text": raw_text[:5000], # Send first 5000 chars to Gemini
                        "contact_icon": contact_icon_str
                    })
                    
            except Exception as e:
                print(f"Error extracting istock links: {e}")
                
            browser.close()
            print(f"Scraping completed. Found {len(results)} items.")
            
        return results
