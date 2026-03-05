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

    def login(self, page, context):
        """Perform login and save session state."""
        print("Checking login status...")
        
        username = os.getenv('LIVING_INSIDER_USERNAME')
        password = os.getenv('LIVING_INSIDER_PASSWORD')
        
        if not username or not password:
            print("Warning: Login credentials not found. Proceeding as guest.")
            return

        page.goto('https://www.livinginsider.com/', wait_until='networkidle')
        self.random_sleep(2, 4)
        
        # Check if we are already logged in from the state file
        try:
            # If we can see member elements, we are already logged in
            if page.query_selector("a[href*='member_istock.php']"):
                print("Session active! No need to login again.")
                return
        except:
            pass

        print("Session expired or not found. Performing login...")
        
        try:
            page.wait_for_selector('#login_username', timeout=10000)
            page.fill('#login_username', username)
            
            page.click('button.btn-next-step[data-step="1"]')
            self.random_sleep(1, 2)
            
            page.wait_for_selector('#password', state='visible', timeout=10000)
            page.fill('#password', password)
            
            page.click('button.btn-next-step[data-step="2"]')
            
            # Wait for navigation or successful login indicator
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
            page.click('#btn_dropdown_ownertype')
            self.random_sleep(0.5, 1.5)
            
            page.click('li.dropdown-ownertype-data[data-key="1"] a')
            self.random_sleep(2, 4) 
        except Exception as e:
            print(f"Error selecting owner filter: {e}")

    def scrape_living_insider(self, target_url):
        results = []
        
        # Cloud setup requires headless and no-sandbox
        launch_args = {
            "headless": True, # Always Headless for Cloud/Docker
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
            
            print("Navigating to member istock area...")
            page.goto('https://www.livinginsider.com/member_istock.php', wait_until='networkidle')
            self.random_sleep(3, 6)

            self.select_owner(page)

            print("Extracting istock detailing URLs...")
            try:
                page.wait_for_selector("a[href*='istockdetail/']", timeout=10000)
                link_elements = page.query_selector_all("a[href*='istockdetail/']")
                
                unique_urls = set()
                for el in link_elements:
                    href = el.get_attribute('href')
                    if href:
                        if not href.startswith('http'):
                            href = f"https://www.livinginsider.com{href}"
                        unique_urls.add(href)
                
                url_list = list(unique_urls)
                
                for index, url in enumerate(url_list):
                    if index >= 3: # Limit for testing, you can remove this later
                        break
                        
                    print(f"\nProcessing Detail URL {index + 1}: {url}")
                    listing_id = url.split('/')[-1].replace('.html', '')
                    
                    # 4. Navigate into Detail Page!
                    detail_page = context.new_page()
                    stealth_sync(detail_page)
                    detail_page.goto(url, wait_until='networkidle')
                    self.random_sleep(2, 4)
                    
                    # Instead of parsing everything with code, we get all raw text 
                    # and let Gemini's NLP do the heavy lifting!
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
                        "raw_text": raw_text[:5000] # Send first 5000 chars to Gemini
                    })
                    
            except Exception as e:
                print(f"Error extracting istock links: {e}")
                
            browser.close()
            print(f"Scraping completed. Found {len(results)} items.")
            
        return results
