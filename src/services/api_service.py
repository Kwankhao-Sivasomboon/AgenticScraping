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
        
    def authenticate(self):
        """
        Login as agent and get the token.
        """
        if self.token:
            return True # Token already provided via .env
            
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
            
    def _get_auth_headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }

    def create_property(self, payload, retry_on_401=True):
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
                    return self.create_property(payload, retry_on_401=False) # ลองใหม่ครั้งเดียว
            
            # Check for conflict/duplicate
            if response.status_code == 409:
                print("⚠️ Property already exists (Duplicate).")
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
