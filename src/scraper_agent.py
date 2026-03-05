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
        try:
            print("Checking for blocking banners...")
            # Safely click just the ad close buttons without destroying the modal framework
            page.evaluate("""
                var closeBtns = document.querySelectorAll('.btn-close[data-dismiss="modal"], .btn-close[onclick*="closeBanner"], a[onclick*="closeBannerAcceptAgent"]');
                closeBtns.forEach(btn => btn.click());
            """)
            self.random_sleep(1, 2)
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
            
        # Check if we are already logged in from the state file
        try:
            # We must check if the element is actually visible, because hidden DOM nodes can cause false positives
            dashboard_element = page.query_selector("a[href*='logout']")
            profile_element = page.query_selector(".profile-name")
            
            if (dashboard_element and dashboard_element.is_visible()) or (profile_element and profile_element.is_visible()):
                # Also double check that the login modal isn't popping up over everything
                if not page.is_visible('.list-login') and not page.is_visible('.email-login') and not page.is_visible('#login_username'):
                    print("Session active! No need to login again.")
                    return
        except:
            pass

        print("Session expired or not found. Performing login...")
        
        try:
            # Wait for either the history profile or the username input
            page.wait_for_selector('.list-login, .email-login, #login_username', timeout=10000)
            
            if page.is_visible('.list-login') or page.is_visible('.email-login'):
                if page.is_visible('.list-login'):
                    print("Found History Login profile (.list-login). Clicking to use it...")
                    page.click('.list-login', force=True)
                else:
                    print("Found History Login profile (.email-login). Clicking to use it...")
                    page.click('.email-login', force=True)
                
                self.random_sleep(1, 2)
                
                # Wait for password input to appear and fill it
                try:
                    page.wait_for_selector('#password', state='visible', timeout=10000)
                    page.fill('#password', password)
                except Exception as e:
                    print("Password field did not appear after clicking history profile, continuing...", e)
                    
                page.click('button.btn-next-step[data-step="2"]', force=True)
                self.random_sleep(3, 5)
                print("History login completed.")
            else:
                print("Standard login form found. Entering credentials...")
                page.fill('#login_username', username)
                page.click('button.btn-next-step[data-step="1"]')
                self.random_sleep(1, 2)
                
                page.wait_for_selector('#password', state='visible', timeout=10000)
                page.fill('#password', password)
                page.click('button.btn-next-step[data-step="2"]')
                self.random_sleep(3, 5)
                
            print("Login completed successfully.")
            
            # SAVE SESSION!
            context.storage_state(path=self.state_file)
            print("Session state saved! Next run will use this session.")
        except Exception as e:
            print(f"Login failed: {e}")

    def select_owner(self, page):
        """Filter by 'Owner' from the dropdown."""
        print("Selecting 'Owner' filter...")
        try:
            page.wait_for_selector('#btn_dropdown_ownertype', timeout=5000)
            page.locator('#btn_dropdown_ownertype').click()
            self.random_sleep(1, 2)
            
            page.locator('li.dropdown-ownertype-data[data-key="1"] a').click()
            self.random_sleep(2, 4) 
        except Exception as e:
            print(f"Error selecting owner filter: {e}")

    def select_property_type(self, page, p_type="คอนโด"):
        """Filter by Property Type e.g., 'คอนโด', 'บ้าน'"""
        print(f"Selecting Property Type: {p_type}...")
        try:
            page.wait_for_selector('#btn_dropdown_actiontype', timeout=5000)
            page.locator('#btn_dropdown_actiontype').click()
            self.random_sleep(1, 2)
            
            # Use playwright locator to find any a tag that contains the text
            # This triggers the javascript event properly
            property_element = page.locator(f"li.dropdown-actiontype-data a:has-text('{p_type}')").first
            if property_element.count() > 0:
                property_element.click()
            else:
                # Fallback to pure onclick search
                page.locator(f"a[onclick*=\"'{p_type}'\"]").first.click()
                
            self.random_sleep(2, 4)
        except Exception as e:
            print(f"Error selecting property type: {e}")

    def search_zone(self, page, zone_keyword="อ่อนนุช"):
        """Search and select a specific zone/location."""
        print(f"Searching for zone: {zone_keyword}...")
        try:
            # 1. Open the search input modal by clicking the wrapper
            try:
                page.wait_for_selector('#box-input-search', timeout=3000)
                page.locator('#box-input-search').click()
                self.random_sleep(1, 1.5)
            except:
                pass
                
            # 2. Type into the specific input to trigger AJAX suggestions
            page.wait_for_selector('#search_zone', timeout=5000)
            
            # Clear using native method
            page.locator('#search_zone').fill('')
            page.locator('#search_zone').press_sequentially(zone_keyword, delay=150)
            
            self.random_sleep(0.5, 1) # Wait just a bit before hitting enter
            
            # Only hit enter if no follow list appears, or hit enter anyway to trigger form
            page.keyboard.press('Enter')
            print("Pressed Enter for #search_zone")
            
            # Check the modal version just in case
            try:
                if page.locator('#search_zone_follow').is_visible():
                    page.locator('#search_zone_follow').fill('')
                    page.locator('#search_zone_follow').press_sequentially(zone_keyword, delay=150)
                    self.random_sleep(0.5, 1)
                    page.keyboard.press('Enter')
                    print("Pressed Enter for #search_zone_follow")
            except:
                pass

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
            page = context.new_page()
            stealth_sync(page)
            
            # Execute Login (will skip if session is valid)
            self.login(page, context)
            
            # Since login now lands on member_istock.php, we just need to ensure URL is correct
            if "member_istock" not in page.url:
                print("Navigating to member istock area...")
                page.goto('https://www.livinginsider.com/member_istock.php', wait_until='domcontentloaded', timeout=60000)
                self.random_sleep(3, 6)
            
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
                        # Check for LINE icon
                        line_icon = detail_page.locator('img[src*="icon-line-new-design.svg"], img[alt="line"]').first
                        if line_icon.is_visible():
                            contact_icon_text.append("Line_Icon: Available")
                    except:
                        pass
                        
                    contact_icon_str = ", ".join(contact_icon_text) if contact_icon_text else "None"
                    # ----------------------------------------
                    
                    # Extract raw text
                    raw_text = detail_page.evaluate("document.body.innerText")
                    
                    # Extract Images URL
                    images = detail_page.query_selector_all('img')
                    image_urls = []
                    for img in images:
                        src = img.get_attribute('src')
                        if src and 'http' in src and 'upload' in src: # Filter only uploaded property images mostly
                            image_urls.append(src)
                    
                    detail_page.close()
                    
                    results.append({
                        "listing_id": listing_id,
                        "url": url,
                        "images": image_urls[:5], # Keep top 5 images
                        "raw_text": raw_text[:5000], # Send first 5000 chars to Gemini
                        "contact_icon": contact_icon_str
                    })
                    
            except Exception as e:
                print(f"Error extracting istock links: {e}")
                
            browser.close()
            print(f"Scraping completed. Found {len(results)} items.")
            
        return results
