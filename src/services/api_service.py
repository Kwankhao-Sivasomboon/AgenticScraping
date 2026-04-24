import os
import requests
import time
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

class APIService:
    def __init__(self, email=None, password=None):
        self.base_url = os.getenv('AGENT_API_BASE_URL', 'http://localhost/api')
        
        # เก็บกุญแจทั้ง 2 ชุดไว้ในตัวครับ
        self.primary_email = os.getenv('AGENT_API_EMAIL')
        self.primary_password = os.getenv('AGENT_API_PASSWORD')
        self.arnon_email = os.getenv('AGENT_ARNON_EMAIL')
        self.arnon_password = os.getenv('AGENT_ARNON_PASSWORD')

        # เลือกเมล์ที่จะใช้เริ่มต้น
        self.email = email or self.primary_email or self.arnon_email or 'agent@example.com'
        self.password = password or self.primary_password or self.arnon_password or 'password123'
        self.token = os.getenv('AGENT_API_TOKEN')
        
        # Staff Credentials
        self.staff_email = os.getenv('STAFF_API_EMAIL') or os.getenv('AGENT_API_EMAIL_COLOR') or self.email
        self.staff_password = os.getenv('STAFF_API_PASSWORD') or os.getenv('AGENT_API_PASSWORD_COLOR') or self.password
        self.staff_token = os.getenv('STAFF_API_TOKEN')
        
    def authenticate(self, use_arnon=False):
        """
        [AGENT] Login to Agent API to get access token.
        ถ้า use_arnon=True จะบังคับใช้เมล์ของคุณ Arnon ครับ
        """
        if use_arnon:
            if not self.arnon_email:
                print("❌ Cannot use Arnon fallback: AGENT_ARNON_EMAIL not set.")
                return False
            self.email = self.arnon_email
            self.password = self.arnon_password
            self.token = None 
        else:
            self.email = self.primary_email
            self.password = self.primary_password
        
        if self.token: return True
        
        base = self.base_url.rstrip('/')
        login_url = f"{base}/agent/login" if '/api' in base else f"{base}/api/agent/login"
            
        payload = {"email": self.email, "password": self.password}
        
        print(f"🔐 Authenticating Agent API...")
        print(f"   📧 Using Email: '{self.email}'")
        print(f"   🌐 URL Target: {login_url}")
        
        try:
            response = requests.post(login_url, json=payload, timeout=20)
            if response.status_code == 200:
                res_json = response.json()
                self.token = res_json.get('token') or res_json.get('data', {}).get('token')
                
                if self.token:
                    print(f"✅ Agent Authentication Successful for '{self.email}'.")
                    return True
                else:
                    print(f"❌ Failed to extract token from login response: {res_json}")
                    return False
            else:
                print(f"❌ Agent Auth Failed ({response.status_code}): {response.text}")
                return False
        except Exception as e:
            print(f"❌ Agent Auth Error: {e}")
            return False

    def authenticate_staff(self):
        """
        [STAFF] Login to Staff API for data uploads.
        Endpoint: /api/staff/login
        """
        if self.staff_token: return True
        
        # สำหรับ STAFF ให้ยิงไปที่ /api/staff/login
        base = self.base_url.rstrip('/')
        if '/api' in base:
             staff_login_url = base + "/staff/login"
        else:
             staff_login_url = base + "/api/staff/login"
             
        payload = {"email": self.staff_email, "password": self.staff_password}
        
        print(f"🔐 Authenticating STAFF API ({self.staff_email})...")
        try:
            response = requests.post(staff_login_url, json=payload, timeout=20)
            if response.status_code == 200:
                res_json = response.json()
                # 🕵️‍♂️ ดักจับ Token ทั้งแบบ Root และแบบที่อยู่ใน Data ห่อหุ้ม
                self.staff_token = res_json.get('token') or res_json.get('data', {}).get('token')
                
                if self.staff_token:
                    print(f"✅ Staff Authentication Successful for '{self.staff_email}'.")
                    return True
                else:
                    print(f"❌ Failed to extract staff token: {res_json}")
                    return False
            else:
                print(f"❌ Staff Auth Failed ({response.status_code}): {response.text}")
                return False
        except Exception as e:
            print(f"❌ Staff Auth Error: {e}")
            return False

            
    def _get_auth_headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _get_staff_auth_headers(self):
        # Always prioritize staff_token for staff endpoints
        token = self.staff_token or self.token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }




    def refresh_photo_urls(self, image_ids):
        """
        Refresh photo URLs by their image_ids.
        Target: {{base_url}}/agent/refresh/photo-urls
        """
        # ถอด /api ออกจากท้าย base_url (ถ้ามี) เพื่อให้ได้ Root สำหรับ URL พิเศษนี้
        base = self.base_url.replace('/api', '').rstrip('/')
        url = f"{base}/agent/refresh/photo-urls"
        
        headers = self._get_auth_headers()
        payload = {"image_ids": image_ids}
        
        print(f"🌐 Refreshing via: {url}")
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            if response.status_code == 404:
                # ลองแบบใส่ /api/agent กลับเข้าไป (เผื่อในกรณีที่เป็น API มาตรฐาน)
                url_fallback = f"{base}/api/agent/refresh/photo-urls"
                response = requests.post(url_fallback, json=payload, headers=headers, timeout=20)

            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Failed to refresh photo URLs: {e}")
            return None

    def create_property(self, payload, retry_on_401=True, duplicate_attempt=0):
        """
        Create a property via the API with duplicate handling (409/422).
        """
        import re
        print(f"🏠 [API] Creating Property: '{payload.get('name')}'...")
        url = f"{self.base_url}/api/agent/properties"
        headers = self._get_auth_headers()
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
            # --- 1. Handle Token Expiry (401) ---
            if response.status_code == 401 and retry_on_401:
                print("⚠️ Token หมดอายุ (401)! กำลังพยายาม Login ใหม่...")
                self.token = None 
                if self.authenticate():
                    return self.create_property(payload, retry_on_401=False, duplicate_attempt=duplicate_attempt)

            # --- 2. Handle Conflict/Duplicate (409 or 422) ---
            if response.status_code in [409, 422]:
                res_body = response.text
                print(f"⚠️ API Info/Validation Warning ({response.status_code})")
                
                try:
                    res_json = response.json()
                    errors = res_json.get("error", {}).get("errors") or res_json.get("errors")
                    if errors:
                        print("   🔍 Specific Validation Errors:")
                        for field, msg in errors.items():
                            print(f"      - {field}: {msg}")
                except:
                    print(f"   📥 Raw Response: {res_body}")
                
                # --- 🚫 Logic ขยับพิกัดหลบ Duplicate (Random Jitter) ---
                if duplicate_attempt < 5:
                    duplicate_attempt += 1
                    import random
                    
                    # สุ่มพิกัดกระจายออกไปในรัศมีเพื่อหาที่ว่าง (ประมาณ 100-500 เมตร)
                    offset_lat = random.uniform(-0.005, 0.005)
                    offset_lng = random.uniform(-0.005, 0.005)
                    
                    if 'latitude' in payload and payload['latitude']:
                        payload['latitude'] = float(payload['latitude']) + offset_lat
                    if 'longitude' in payload and payload['longitude']:
                        payload['longitude'] = float(payload['longitude']) + offset_lng

                    print(f"🔄 Duplicate Workaround: สลัดพิกัดใหม่ (Random) และพยายามอีกครั้ง (Attempt {duplicate_attempt}/5)...")
                    time.sleep(random.uniform(1.0, 3.0)) # 🐢 พักนิดนึงเพื่อให้ Server ไม่มึน
                    return self.create_property(payload, retry_on_401=retry_on_401, duplicate_attempt=duplicate_attempt)
                else:
                    print(f"❌ Failed to resolve duplicate after {duplicate_attempt} attempts.")
                    print(f"📥 Last API Full Response: {res_body}")
                    return None
                    return None

            # --- 3. Handle Success ---
            response.raise_for_status()
            data = response.json()
            property_id = data.get('id') or data.get('data', {}).get('id')
            
            if property_id:
               print(f"✅ Property created successfully. ID: {property_id}")
            return property_id

        except Exception as e:
            print(f"❌ Failed to create property: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None

    def get_property_status(self, property_id):
        """
        [NEW] ดึงสถานะปัจจุบันของ Property จาก API โดยตรง
        URL: /api/agent/properties/{property_id}/status
        ใช้เพื่อเช็คว่า 'Approved' หรือยังก่อนที่จะซิงค์ทับ
        """
        url = f"{self.base_url}/api/agent/properties/{property_id}/status"
        headers = self._get_auth_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # คืนค่าก้อนข้อมูลภายใต้ key 'data' (ตามที่บอสส่งตัวอย่างมา)
                return data.get("data") or data
            elif response.status_code == 401:
                print("⚠️ Token หมดอายุ (401)! กำลัง Login ใหม่เพื่อเช็ค Status...")
                self.token = None 
                if self.authenticate():
                    return self.get_property_status(property_id)
            return None
        except Exception as e:
            print(f"🕵️‍♂️ [Status Warn] ไม่สามารถเช็ค Status ของ {property_id} ได้: {e}")
            return None

    def update_property(self, property_id, payload):
        """
        Update an existing Property via Agent API.
        URL: https://app.yourhome.co.th/api/agent/properties/{property_id}/update
        """
        print(f"🏠 Updating Property {property_id} via API...")
        url = f"{self.base_url}/api/agent/properties/{property_id}/update"
        headers = self._get_auth_headers()
        
        try:
            # ใช้ POST (อาจจะใช้ PATCH หรือ PUT ก็ได้แล้วแต่บอคที่รับ แต่นิยมใช้ POST หากลงท้ายด้วย /update)
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code in [200, 201]:
                print(f"✅ Property {property_id} updated successfully.")
                return True
            else:
                print(f"⚠️ API returned {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Failed to update property {property_id}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                # --- [เพิ่ม] จัดการ Token หมดอายุ (401) ระหว่างทาง ---
                if e.response.status_code == 401:
                    print("⚠️ Token หมดอายุ (401)! กำลังพยายาม Login ใหม่เพื่อขอ Token...")
                    self.token = None 
                    if self.authenticate():
                        return self.update_property(property_id, payload)
                print(f"Response Body: {e.response.text}")
            return False


    def create_activity(self, property_id, payload, retry_on_401=True):
        """
        Create a new activity (call, accept, deny) for a Property via Agent API.
        URL: /agent/properties/{property_id}/activities
        """
        import json
        
        # กรอง notes ให้เป็น ASCII-safe ก่อนส่ง (ป้องกันปัญหา Thai chars)
        safe_payload = dict(payload)
        if "notes" in safe_payload and safe_payload["notes"]:
            safe_payload["notes"] = safe_payload["notes"].encode("utf-8", errors="replace").decode("utf-8")

        print(f"📝 Logging Activity for Property {property_id}...")
        print(f"   📤 Request URL: {self.base_url}/api/agent/properties/{property_id}/activities")
        print(f"   📤 Request Body: {json.dumps(safe_payload, ensure_ascii=False)}")
        
        url = f"{self.base_url}/api/agent/properties/{property_id}/activities"
        headers = self._get_auth_headers()
        
        try:
            response = requests.post(url, json=safe_payload, headers=headers, timeout=20)
            
            print(f"   📥 Response Status: {response.status_code}")
            print(f"   📥 Response Body: {response.text[:500]}")
            
            if response.status_code == 401 and retry_on_401:
                 print("⚠️ Token หมดอายุ (401)! กำลังพยายาม Login ใหม่เพื่อขอ Token...")
                 self.token = None 
                 if self.authenticate():
                     return self.create_activity(property_id, payload, retry_on_401=False)
            
            if response.status_code in [200, 201]:
                print(f"✅ Activity logged successfully.")
                return True
            else:
                print(f"⚠️ Failed to log Activity. API returned {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Failed to log activity for {property_id}: {e}")
            return False
    def get_property_status(self, property_id, retry_on_401=True):
        """
        Get approval_status of a Property.
        GET /api/agent/properties/{property_id}/status
        """
        url = f"{self.base_url}/api/agent/properties/{property_id}/status"
        headers = self._get_auth_headers()
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 401 and retry_on_401:
                self.token = None
                if self.authenticate():
                    return self.get_property_status(property_id, retry_on_401=False)
            if response.status_code == 200:
                data = response.json()
                res_data = data.get("data") if isinstance(data.get("data"), dict) else data
                return res_data.get("approval_status") or data.get("approval_status")
            return None
        except Exception as e:
            print(f"   ⚠️ Error ดึงสถานะ {property_id}: {e}")
            return None


    def upload_photos(self, property_id, memory_files, batch_size=5, retry_on_401=True):
        """
        Upload photos for a property in batches to prevent 500 Server Errors.
        memory_files is a list of tuples: (filename, BytesIO_object)
        """
        import time
        import random
        if not property_id or not memory_files:
            return False
            
        print(f"📸 Total photos to upload: {len(memory_files)} (Batched by {batch_size})")
        for start_idx in range(0, len(memory_files), batch_size):
            batch = memory_files[start_idx : start_idx + batch_size]
            print(f"   📤 Uploading batch {start_idx // batch_size + 1}... ({len(batch)} photos)")
            
            url = f"{self.base_url}/api/agent/upload/photos"
            headers = self._get_auth_headers()
            if "Content-Type" in headers:
                del headers["Content-Type"]
            headers["Accept"] = "application/json"
            
            files = {}
            data = {"property_id": property_id}
            
            for i, (filename, file_io) in enumerate(batch):
                # We can keep i starting from 0 for each batch as the API usually adds to the existing gallery
                files[f"photos[{i}][file]"] = (filename, file_io, "image/jpeg")
                data[f"photos[{i}][tag]"] = "gallery"
                data[f"photos[{i}][facing_direction]"] = ""
                
            try:
                response = requests.post(url, headers=headers, data=data, files=files, timeout=60)
                
                if response.status_code == 401 and retry_on_401:
                    print("⚠️ Token หมดอายุ (401)! กำลังพยายาม Login ใหม่เพื่อขอ Token...")
                    self.token = None 
                    if self.authenticate():
                        return self.upload_photos(property_id, memory_files, retry_on_401=False)
                
                response.raise_for_status()
                print(f"   ✅ Batch {start_idx // batch_size + 1} uploaded successfully.")
                
                if start_idx + batch_size < len(memory_files):
                    delay = random.uniform(1.0, 2.0)
                    print(f"   💤 Waiting {delay:.1f}s before next batch...")
                    time.sleep(delay)
                    
            except Exception as e:
                print(f"❌ Failed to upload batch {start_idx // batch_size + 1}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                     print(f"Response: {e.response.text}")
                return False # If one batch fails, we consider the whole property upload risky
                
        return True

    def refresh_photo_urls(self, image_ids, retry_on_401=True):
        """
        Refresh S3 Signed URLs for a list of internal image IDs.
        POST {{base_url}}/api/agent/refresh/photo-urls
        """
        if not image_ids:
            return []
            
        print(f"🔄 Refreshing Signed URLs for {len(image_ids)} images...")
        url = f"{self.base_url}/api/agent/refresh/photo-urls"
        headers = self._get_auth_headers()
        payload = {"image_ids": image_ids}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            if response.status_code == 401 and retry_on_401:
                self.token = None
                if self.authenticate():
                    return self.refresh_photo_urls(image_ids, retry_on_401=False)
                    
            response.raise_for_status()
            data = response.json()
            
            # Print raw response to debug structure
            print(f"📡 Refresh Response Raw: {response.text[:500]}")
            
            return data.get('data', [])

        except Exception as e:
            print(f"❌ Failed to refresh photo URLs: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return []

    def submit_color_analysis(self, payload):
        """
        Submit Color Analysis to staff API endpoint.
        POST {{base_url}}/api/staff/color-analyses
        """
        print(f"🎨 Submitting Color Analysis to Staff API...")
        
        base = self.base_url.rstrip('/')
        if '/api' in base:
            url = f"{base}/staff/color-analyses"
        else:
            url = f"{base}/api/staff/color-analyses"
            
        print(f"   🌐 Staff Target: {url}")
        headers = self._get_staff_auth_headers()
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 401:
                # ลอง Login Staff ใหม่ถ้า Token หมดอายุ
                if self.authenticate_staff():
                    headers = self._get_staff_auth_headers()
                    response = requests.post(url, json=payload, headers=headers, timeout=30)

            if response.status_code in [200, 201]:
                print(f"✅ Color Analysis submitted successfully.")
                return True
            else:
                print(f"⚠️ Staff API returned {response.status_code}: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Failed to submit color analysis: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return False



