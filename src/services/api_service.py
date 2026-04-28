import os
import requests
import time
from urllib.parse import urljoin
from dotenv import load_dotenv

load_dotenv()

class APIService:
    def __init__(self, email=None, password=None, primary_env=None):
        # 1. Initialize Firestore to fetch dynamic config
        from src.services.firestore_service import FirestoreService
        fs = FirestoreService()
        db_config = {}
        try:
            # พยายามดึงจาก collection 'config' document 'api'
            doc = fs.db.collection('config').document('api').get()
            if doc.exists:
                db_config = doc.to_dict()
                print("📡 Config: Loaded from Firestore (config/api)")
        except Exception as e:
            print(f"⚠️ Config: Could not load from Firestore: {e}")

        # 2. Setup URLs (Force Parameter > Firestore > Environment > Default)
        self.primary_url = primary_env or db_config.get('AGENT_API_PRIMARY_URL') or os.getenv('AGENT_API_PRIMARY_URL') or 'https://app.yourhome.co.th'
        self.fallback_url = db_config.get('AGENT_API_FALLBACK_URL') or os.getenv('AGENT_API_FALLBACK_URL') or 'https://staging.yourhome.co.th'
        self.base_url = self.primary_url
        
        # 3. Setup Credentials (Prioritize Firestore > Environment)
        self.primary_email = db_config.get('AGENT_API_EMAIL') or os.getenv('AGENT_API_EMAIL')
        self.primary_password = db_config.get('AGENT_API_PASSWORD') or os.getenv('AGENT_API_PASSWORD')
        self.arnon_email = db_config.get('AGENT_ARNON_EMAIL') or os.getenv('AGENT_ARNON_EMAIL')
        self.arnon_password = db_config.get('AGENT_ARNON_PASSWORD') or os.getenv('AGENT_ARNON_PASSWORD')

        self.email = email or self.primary_email or self.arnon_email or 'agent@example.com'
        self.password = password or self.primary_password or self.arnon_password or 'password123'
        self.token = os.getenv('AGENT_API_TOKEN') # Token มักจะเป็น Dynamic
        
        self.staff_email = db_config.get('STAFF_API_EMAIL') or os.getenv('STAFF_API_EMAIL') or os.getenv('AGENT_API_EMAIL_COLOR') or self.email
        self.staff_password = db_config.get('STAFF_API_PASSWORD') or os.getenv('STAFF_API_PASSWORD') or os.getenv('AGENT_API_PASSWORD_COLOR') or self.password
        self.staff_token = os.getenv('STAFF_API_TOKEN')
        
    def _request_with_fallback(self, method, endpoint, **kwargs):
        """Helper to handle primary -> fallback failover"""
        # เตรียม URL
        def get_full_url(base):
            b = base.rstrip('/')
            # ถ้า Base URL ไม่มี /api ให้เติมเข้าไปก่อน
            if '/api' not in b.lower():
                b = f"{b}/api"
            
            # ทำความสะอาด endpoint (เอา / ข้างหน้าออกถ้ามี)
            clean_endpoint = endpoint.lstrip('/')
            return f"{b}/{clean_endpoint}"

        # 1. Try Primary
        try:
            full_url = get_full_url(self.primary_url)
            print(f"📡 {method} -> Primary: {full_url}")
            response = requests.request(method, full_url, **kwargs)
            if response.status_code < 500: return response
            print(f"⚠️ Primary returned {response.status_code}. Trying fallback...")
        except Exception as e:
            print(f"⚠️ Primary Connection Error: {e}. Trying fallback...")

        # 2. Try Fallback
        if self.fallback_url:
            try:
                full_url = get_full_url(self.fallback_url)
                print(f"📡 {method} -> Fallback: {full_url}")
                response = requests.request(method, full_url, **kwargs)
                if response.status_code < 500:
                    # ✅ ถ้า Fallback สำเร็จ ให้สลับมาใช้เป็น URL หลักถาวรสำหรับ Instance นี้เลย
                    print(f"🔄 Failover Successful: Switching to Fallback URL permanently.")
                    self.primary_url = self.fallback_url 
                    self.base_url = self.fallback_url
                    return response
                return response
            except Exception as e:
                print(f"❌ Fallback also failed: {e}")
        return None

    def authenticate(self, use_arnon=False):
        if use_arnon:
            self.email = self.arnon_email
            self.password = self.arnon_password
            self.token = None 
        else:
            self.email = self.primary_email
            self.password = self.primary_password
        
        if self.token: return True
        payload = {"email": self.email, "password": self.password}
        print(f"🔐 Authenticating Agent API...")
        response = self._request_with_fallback("POST", "/agent/login", json=payload, timeout=20)
        if response and response.status_code == 200:
            res_json = response.json()
            self.token = res_json.get('token') or res_json.get('data', {}).get('token')
            if self.token:
                print(f"✅ Agent Auth Success for '{self.email}'.")
                return True
        print(f"❌ Agent Auth Failed.")
        return False

    def authenticate_staff(self):
        if self.staff_token: return True
        payload = {"email": self.staff_email, "password": self.staff_password}
        print(f"🔐 Authenticating STAFF API ({self.staff_email})...")
        response = self._request_with_fallback("POST", "/staff/login", json=payload, timeout=20)
        if response and response.status_code == 200:
            res_json = response.json()
            self.staff_token = res_json.get('token') or res_json.get('data', {}).get('token')
            if self.staff_token:
                print(f"✅ Staff Auth Success for '{self.staff_email}'.")
                return True
        print(f"❌ Staff Auth Failed.")
        return False

    def _get_auth_headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json"}

    def _get_staff_auth_headers(self):
        token = self.staff_token or self.token
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}

    def update_property(self, property_id, payload):
        print(f"🏠 Updating Property {property_id}...")
        headers = self._get_auth_headers()
        # 1. ลองแบบเดิมก่อน (/update)
        response = self._request_with_fallback("POST", f"/agent/properties/{property_id}/update", json=payload, headers=headers, timeout=30)
        
        # 2. ถ้าแบบเดิมหาไม่เจอ (404) ลองแบบไม่มี /update (Standard POST)
        if response and response.status_code == 404:
            print(f"⚠️ /update not found for {property_id}. Trying base URL...")
            response = self._request_with_fallback("POST", f"/agent/properties/{property_id}", json=payload, headers=headers, timeout=30)
            
        if response:
            if response.status_code in [200, 201]:
                print(f"✅ Property {property_id} updated.")
                return True
            elif response.status_code == 401:
                self.token = None
                if self.authenticate(): return self.update_property(property_id, payload)
        return False

    def submit_color_analysis(self, payload):
        print(f"🎨 Submitting Color Analysis to Staff API...")
        headers = self._get_staff_auth_headers()
        response = self._request_with_fallback("POST", "/staff/color-analyses", json=payload, headers=headers, timeout=30)
        if response:
            if response.status_code in [200, 201]:
                print(f"✅ Color Analysis submitted.")
                return True
            elif response.status_code == 401:
                if self.authenticate_staff(): return self.submit_color_analysis(payload)
        return False

    def refresh_photo_urls(self, image_ids, retry_on_401=True):
        if not image_ids: return []
        print(f"🔄 Refreshing Signed URLs for {len(image_ids)} images...")
        payload = {"image_ids": image_ids}
        response = self._request_with_fallback("POST", "/agent/refresh/photo-urls", json=payload, timeout=20)
        if response:
            if response.status_code == 401 and retry_on_401:
                self.token = None
                if self.authenticate(): return self.refresh_photo_urls(image_ids, False)
            if response.status_code == 200:
                data = response.json()
                return data.get('data', [])
        return []

    def get_property_detail(self, property_id, retry_on_401=True):
        headers = self._get_auth_headers()
        response = self._request_with_fallback("GET", f"/agent/properties/{property_id}/status", headers=headers, timeout=15)
        if response:
            if response.status_code == 401 and retry_on_401:
                self.token = None
                if self.authenticate(): return self.get_property_detail(property_id, False)
            if response.status_code == 200:
                res_json = response.json()
                return res_json.get('data', res_json)
            elif response.status_code in [403, 401]:
                return "forbidden"
        return None

    def get_property_status(self, property_id, retry_on_401=True):
        headers = self._get_auth_headers()
        response = self._request_with_fallback("GET", f"/agent/properties/{property_id}/status", headers=headers, timeout=20)
        if response:
            if response.status_code == 401 and retry_on_401:
                self.token = None
                if self.authenticate(): return self.get_property_status(property_id, False)
            if response.status_code == 200:
                data = response.json()
                res_data = data.get("data") if isinstance(data.get("data"), dict) else data
                return res_data.get("approval_status") or data.get("approval_status")
        return None

    def upload_photos(self, property_id, memory_files, batch_size=5, retry_on_401=True):
        if not property_id or not memory_files: return False
        for start_idx in range(0, len(memory_files), batch_size):
            batch = memory_files[start_idx : start_idx + batch_size]
            headers = self._get_auth_headers()
            if "Content-Type" in headers: del headers["Content-Type"]
            files = {}
            data = {"property_id": property_id}
            for i, (filename, file_io) in enumerate(batch):
                files[f"photos[{i}][file]"] = (filename, file_io, "image/jpeg")
                data[f"photos[{i}][tag]"] = "gallery"
            response = self._request_with_fallback("POST", "/agent/upload/photos", headers=headers, data=data, files=files, timeout=60)
            if response and response.status_code == 401 and retry_on_401:
                self.token = None
                if self.authenticate(): return self.upload_photos(property_id, memory_files, batch_size, False)
            if not response or response.status_code not in [200, 201]: return False
        return True
