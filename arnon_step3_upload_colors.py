import os
import time
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# 🎯 [CONFIG] ระบุช่วงของ Property ID ที่ต้องการอัปโหลดข้อมูลสีเข้าระบบ Staff
START_ID = 428
END_ID = 428

# Predefined 14 colors in Thai
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู", 
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

def upload_arnon_analysis():
    fs = FirestoreService()
    
    # 🚀 ปล่อยให้ APIService เลือก Email/Password ฝั่ง Staff จาก .env เองอัตโนมัติ
    api = APIService()
    
    if not api.authenticate_staff():
        print("Staff Authentication failed. Please check STAFF_API_EMAIL in .env")
        return

    print(f"Starting upload for IDs: {START_ID} ถึง {END_ID}...")

    for pid in range(START_ID, END_ID + 1):
        prop_id = str(pid)
        doc_ref = fs.db.collection("ARNON_properties").document(prop_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            print(f"⚠️ Skip {prop_id}: ไม่พบข้อมูลใน Firestore (ต้องรัน Step 1/2 ก่อน)")
            continue
            
        data = doc.to_dict()
        
        # กรองเอาเฉพาะตัวที่วิเคราะห์แล้ว
        if not data.get("analyzed"):
            print(f"⚠️ Skip {prop_id}: ยังไม่ได้วิเคราะห์สี (Analyzed=False)")
            continue
        
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
        from datetime import datetime
        now_iso = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        payload = {
            "property_id": int(prop_id),
            "analyzed_at": now_iso, # 🕒 เพิ่มเวลาที่วิเคราะห์จริง
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
