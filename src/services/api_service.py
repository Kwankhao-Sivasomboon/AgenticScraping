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
        url = f"{self.base_url}/agent/tokens/create"
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
            data = response.json()
            # Assuming the token is in the response (e.g., data['token'] or data['access_token'])
            self.token = data.get('token') or data.get('access_token')
            print("✅ Agent Authentication Successful.")
            return True
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

    def create_property(self, payload):
        """
        Create a property via the API.
        """
        print("🏠 Creating Property via API...")
        url = f"{self.base_url}/agent/properties"
        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=20)
            
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

    def upload_photos(self, property_id, memory_files):
        """
        Upload photos for a property.
        memory_files is a list of tuples: (filename, BytesIO_object)
        """
        if not property_id or not memory_files:
            return False
            
        print(f"📸 Uploading {len(memory_files)} photos to Property ID: {property_id}...")
        url = f"{self.base_url}/agent/upload/photos"
        headers = self._get_auth_headers()
        
        # requests formatting for multipart form data
        # photos[0][file], photos[1][file]
        files = {}
        data = {
            "property_id": property_id
        }
        
        for i, (filename, file_io) in enumerate(memory_files):
            # field name in multipart must be: photos[i][file]
            files[f"photos[{i}][file]"] = (filename, file_io, "image/jpeg")
            
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
