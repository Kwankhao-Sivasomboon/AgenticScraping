import os
import time
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# Predefined 14 colors in Thai
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู", 
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

def upload_arnon_analysis():
    fs = FirestoreService()
    
    # Login as Staff
    staff_email = os.getenv('AGENT_ARNON_EMAIL')
    staff_pass = os.getenv('AGENT_ARNON_PASSWORD')
    api = APIService(email=staff_email, password=staff_pass)
    
    if not api.authenticate_staff():
        print("Staff Authentication failed.")
        return

    from google.cloud.firestore_v1.base_query import FieldFilter
    # Fetch properties that are analyzed but not yet uploaded
    docs = list(fs.db.collection("ARNON_properties")
                .where(filter=FieldFilter("analyzed", "==", True))
                .where(filter=FieldFilter("uploaded", "==", False))
                .limit(500) 
                .stream())
    
    if not docs:
        print("All analyzed properties have been uploaded.")
        return

    print(f"Starting upload for {len(docs)} properties to Staff API...")

    for doc in docs:
        prop_id = doc.id
        data = doc.to_dict()
        
        # 1. Expand element_furniture from flattened string to List[List[str]]
        raw_furniture = data.get("element_furniture", [])
        formatted_furniture = []
        for s in raw_furniture:
            if isinstance(s, str) and s.strip():
                items = [item.strip() for item in s.split(",") if item.strip()]
                formatted_furniture.append(items)
            else:
                formatted_furniture.append([])
        
        # 2. Determine dominant color Thai name
        furniture_colors = data.get("element_color", [0]*14)
        max_idx = furniture_colors.index(max(furniture_colors)) if any(furniture_colors) else 10
        dominant_color_thai = THAI_COLORS[max_idx]

        # 3. Construct Payload based on Staff API spec
        payload = {
            "property_id": int(prop_id),
            "average_color_hex": "#FFFFFF", 
            "color": dominant_color_thai,
            "room_color": data.get("room_color"),
            "furniture_color": furniture_colors,
            "furniture_elements": formatted_furniture,
            "interior_style": data.get("architect_style", "Other"),
            "property_type": "house"
        }
        
        if api.submit_color_analysis(payload):
            fs.db.collection("ARNON_properties").document(prop_id).update({
                "uploaded": True,
                "uploaded_at": time.time()
            })
            print(f"Property {prop_id} Uploaded.")
        else:
            print(f"Failed to upload property {prop_id}.")
        
        # Add random delay to prevent 500 error
        import random
        delay = random.uniform(2.0, 4.0)
        print(f"Waiting {delay:.1f}s before next upload...")
        time.sleep(delay)

if __name__ == "__main__":
    upload_arnon_analysis()
