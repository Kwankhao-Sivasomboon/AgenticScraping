import os
import requests
import time
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

BASE_URL = os.getenv('AGENT_API_BASE_URL', 'http://localhost/api')
EMAIL = os.getenv('AGENT_ARNON_EMAIL')
PASSWORD = os.getenv('AGENT_ARNON_PASSWORD')

def fetch_arnon_properties_silent():
    api = APIService(email=EMAIL, password=PASSWORD)
    if not api.authenticate():
        print("Login failed.")
        return

    fs = FirestoreService()
    page = 1
    total_properties = 0
    total_images = 0

    print("Fetching Arnon Properties... Please wait.")
    
    while True:
        headers = api._get_auth_headers()
        base = BASE_URL.replace('/api', '').rstrip('/')
        url = f"{base}/api/agent/properties?page={page}"
        
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200:
            print(f"Error: Received status code {res.status_code} at page {page}: {res.text}")
            break
            
        data = res.json()
        properties = []
        
        # ลอจิกเจาะข้อมูล (API ส่งกลับมาเป็น data -> properties)
        if isinstance(data, dict) and "data" in data:
            d1 = data["data"]
            if isinstance(d1, dict) and "properties" in d1:
                properties = d1["properties"]
            elif isinstance(d1, list):
                properties = d1
        
        if not properties:
            break
            
        batch = fs.db.batch()
        for prop in properties:
            prop_id = str(prop.get("id"))
            images = prop.get("images", [])
            
            image_data_list = [{"id": i.get("id"), "url": i.get("url")} for i in images]
            
            doc_ref = fs.db.collection("ARNON_properties").document(prop_id)
            batch.set(doc_ref, {
                "property_id": prop_id,
                "name": prop.get("name"),
                "image_count": len(image_data_list),
                "images": image_data_list,
                "analyzed": False,
                "uploaded": False,
                "updated_at": time.time()
            }, merge=True)
            
            total_properties += 1
            total_images += len(image_data_list)
            
        batch.commit()
        print(f"Page {page} done ({len(properties)} props).")
        page += 1
        time.sleep(0.5)

    print(f"DONE. Found {total_properties} properties and {total_images} images.")

if __name__ == "__main__":
    fetch_arnon_properties_silent()
