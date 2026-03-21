import os
import requests
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

class APIService:
    def __init__(self):
        self.base_url = os.getenv('AGENT_API_BASE_URL', 'http://localhost/api')
        self.email = os.getenv('AGENT_API_EMAIL', 'agent@example.com')
        self.password = os.getenv('AGENT_API_PASSWORD', 'password123')
        self.token = os.getenv('AGENT_API_TOKEN')  # Can provide token directly to bypass login
        
        # Staff Credentials (Using specialized _COLOR variables as requested)
        self.staff_email = os.getenv('AGENT_API_EMAIL_COLOR') or self.email
        self.staff_password = os.getenv('AGENT_API_PASSWORD_COLOR') or self.password
        self.staff_token = os.getenv('STAFF_API_TOKEN')
        
    def authenticate(self):
        """
        Login as agent and get the token (always fresh login).
        """
        # ถ้ามี token ใน .env ให้ใช้เฉพาะตอนยังไม่ได้ Login เท่านั้น
        # (ไม่ข้าม login ถ้ามี token เก่า เพราะอาจ expired)
        if not self.email or not self.password:
            # กรณีที่ไม่มี email/password ใน .env ให้ใช้ token จาก .env แทน
            if self.token:
                print("ℹ️ ใช้ AGENT_API_TOKEN จาก .env (ไม่มี email/password)")
                return True
            print("❌ ไม่มี email/password และไม่มี token ใน .env")
            return False
        
        print("🔐 Authenticating Agent API...")
        url = f"{self.base_url}/api/agent/login"
        payload = {
            "email": self.email,
            "password": self.password
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            res_json = response.json()
            
            # --- ดึง Token จาก data -> token ตามตัวอย่าง Log ---
            data_part = res_json.get('data', {})
            self.token = data_part.get('token')
            
            if self.token:
                print("✅ Agent Authentication Successful.")
                return True
            else:
                print("❌ Authentication Failed: Token not found in response data.")
                return False
        except Exception as e:
            print(f"❌ Authentication Failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return False

    def authenticate_staff(self):
        """
        Login as staff and get the token.
        """
        if not self.staff_email or not self.staff_password:
            if self.staff_token:
                print("ℹ️ Using STAFF_API_TOKEN from .env (no staff credentials)")
                return True
            print("❌ No staff email/password in .env")
            return False
            
        print("🔐 Authenticating Staff API...")
        url = f"{self.base_url}/api/staff/login"
        payload = {"email": self.staff_email, "password": self.staff_password}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            res_json = response.json()
            data_part = res_json.get('data', {})
            self.staff_token = data_part.get('token')
            
            if self.staff_token:
                print("✅ Staff Authentication Successful.")
                return True
            else:
                print("❌ Staff Authentication Failed: Token not found.")
                return False
        except Exception as e:
            print(f"❌ Staff Authentication Failed: {e}")
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




    def create_property(self, payload, retry_on_401=True, duplicate_attempt=0):
        """
        Create a property via the API.
        """
        print("🏠 Creating Property via API...")
        url = f"{self.base_url}/api/agent/properties"
        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
            # --- ปรับปรุงใหม่: แก้ไขปัญหา Token หมดอายุ (401) ---
            if response.status_code == 401 and retry_on_401:
                print("⚠️ Token หมดอายุ (401)! กำลังพยายาม Login ใหม่เพื่อขอ Token...")
                self.token = None # เคลียร์ Token เก่า
                if self.authenticate():
                    return self.create_property(payload, retry_on_401=False, duplicate_attempt=duplicate_attempt)
            
            # --- เช็ค Error Duplicate Name (มักจะเป็น 422 หรือ 409) ---
            if response.status_code in [409, 422]:
                res_txt = response.text.lower()
                # ตรวจจับ Validation Message ของ API ที่เกี่ยวกับ "name", "duplicate", "already been taken", "exists"
                if "name" in res_txt and ("taken" in res_txt or "exist" in res_txt or "duplicate" in res_txt or "ซ้ำ" in res_txt):
                    if duplicate_attempt < 20: # จำกัดการลองสูงสุด 20 ครั้ง
                        duplicate_attempt += 1
                        print(f"⚠️ รายการชื่อซ้ำ (Duplicate Name)! เปลี่ยนชื่อโดยเติม ({duplicate_attempt}) แล้วลองใหม่...")
                        
                        import re
                        # ตัด (1), (2) เดิมที่เคยมีออกก่อน ถ้าชื่อมี suffix อยู่แล้ว
                        base_name = re.sub(r'\s*\(\d+\)$', '', payload.get('name', ''))
                        payload['name'] = f"{base_name} ({duplicate_attempt})"
                        
                        return self.create_property(payload, retry_on_401=retry_on_401, duplicate_attempt=duplicate_attempt)

            # Check for conflict/duplicate (เผื่อไม่ได้ Error ลงที่ชื่อ แต่ลง Property ID)
            if response.status_code == 409:
                print("⚠️ Property already exists (Duplicate). Attempting to retrieve existing ID...")
                try:
                    data = response.json()
                    # พยายามหา ID จาก data.id หรือ data.data.id
                    existing_id = data.get('id') or data.get('data', {}).get('id')
                    if existing_id:
                        print(f"🔗 Linked to existing API Property ID: {existing_id}")
                        return existing_id
                except:
                    pass
                return None
                
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
                print(f"Response: {e.response.text}")
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
        Get the current status and information of a Property from Agent API.
        URL: {{base_url}}/api/agent/properties/{property_id}/status
        """
        print(f"🔍 Fetching Property status for {property_id} via API...")
        url = f"{self.base_url}/api/agent/properties/{property_id}/status"
        headers = self._get_auth_headers()
        
        try:
            response = requests.get(url, headers=headers, timeout=20)
            
            # --- แก้ไขปัญหา Token หมดอายุ (401) ---
            if response.status_code == 401 and retry_on_401:
                print("⚠️ Token หมดอายุ (401)! กำลังพยายาม Login ใหม่เพื่อขอ Token...")
                self.token = None 
                if self.authenticate():
                    return self.get_property_status(property_id, retry_on_401=False)
            
            response.raise_for_status()
            data = response.json()
            return data.get('data') or data  # Return inner data if wrapped, else return whole dict
            
        except Exception as e:
            print(f"❌ Failed to get property status {property_id}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None

    def upload_photos(self, property_id, memory_files):
        """
        Upload photos for a property.
        memory_files is a list of tuples: (filename, BytesIO_object)
        """
        if not property_id or not memory_files:
            return False
            
        print(f"📸 Uploading {len(memory_files)} photos to Property ID: {property_id}...")
        url = f"{self.base_url}/api/agent/upload/photos"
        headers = self._get_auth_headers()
        
        # requests formatting for multipart form data
        # photos[0][file], photos[1][file]
        files = {}
        data = {
            "property_id": property_id
        }
        
        for i, (filename, file_io) in enumerate(memory_files):
            # field name in multipart must be: photos[i][file]
            files[f"photos[{i}][file]"] = (filename, file_io)
            # เพิ่ม tag เข้าไปด้วยเพื่อแก้ Validation Error
            data[f"photos[{i}][tag]"] = "room" 
            
        try:
            response = requests.post(url, headers=headers, data=data, files=files, timeout=60)
            response.raise_for_status()
            print("✅ Photos uploaded successfully.")
            return True
        except Exception as e:
            print(f"❌ Failed to upload photos: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return False

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
        if not self.staff_token:
            self.authenticate_staff()
            
        print(f"🎨 Submitting Color Analysis to /api/staff/color-analyses...")
        url = f"{self.base_url}/api/staff/color-analyses"
        headers = self._get_staff_auth_headers()
        
        try:
            # ใช้ JSON indent=4 เพื่อเลียนแบบ Postman (Backend บางตัวอาจจะเช็คโครงสร้างบรรทัด)
            import json
            formatted_json = json.dumps(payload, indent=4)
            response = requests.post(url, data=formatted_json, headers=headers, timeout=30)
            
            if response.status_code == 401:
                # ลอง Login Staff ใหม่ถ้า Token หมดอายุ
                if self.authenticate_staff():
                    headers = self._get_staff_auth_headers()
                    response = requests.post(url, data=formatted_json, headers=headers, timeout=30)

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



