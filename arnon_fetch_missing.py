import os
import requests
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

def fetch_specific_ids():
    fs = FirestoreService()
    api = APIService(email=os.getenv('AGENT_ARNON_EMAIL'), password=os.getenv('AGENT_ARNON_PASSWORD'))
    api.authenticate()
    
    # ช่วง ID ที่บอสต้องการส่องเป็นพิเศษ
    target_ids = list(range(73, 85)) 
    print(f"Searching for images for IDs: {target_ids}")
    
    headers = api._get_auth_headers()
    base = api.base_url.rstrip('/')
    
    for pid in target_ids:
        print(f" Inspecting ID {pid} via Status & Detail endpoints...")
        
        # ลองส่องที่หลายๆ endpoint ที่อาจจะมีข้อมูลรูปซ่อนอยู่
        endpoints = [
            f"{base}/api/agent/properties/{pid}/status",
            f"{base}/api/agent/properties/{pid}" # ลองตัวหลักด้วย
        ]
        
        found_images = []
        for url in endpoints:
            try:
                r = requests.get(url, headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    # แกะโครงสร้างข้อมูล (มักจะอยู่ใน data หรือ properties)
                    prop_data = data.get("data", {})
                    if not isinstance(prop_data, dict):
                        prop_data = {}
                        
                    images = prop_data.get("images", []) or data.get("images", [])
                    if images:
                        found_images = images
                        print(f"   [Found!] {len(found_images)} images found at {url}")
                        break
            except Exception as e:
                print(f"   Error at {url}: {e}")
                
        if found_images:
            # เก็บลง Firestore เพื่อให้ Step 2 เอาไปใช้ต่อได้
            fs.db.collection("ARNON_properties").document(str(pid)).set({
                "property_id": str(pid),
                "images": found_images,
                "image_count": len(found_images),
                "analyzed": False,
                "uploaded": False
            }, merge=True)
            print(f"   [Saved] Property {pid} added to analysis queue.")
        else:
            print(f"   [Empty] No images found for ID {pid} in any endpoint.")

if __name__ == "__main__":
    fetch_specific_ids()
