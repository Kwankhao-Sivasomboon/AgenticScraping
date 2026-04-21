import os
import time
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# ⚙️ ตั้งค่าคอลเลกชันที่ต้องการดึงข้อมูล (เปลี่ยนเป็น 'ARNON_properties' ได้ที่นี่)
SOURCE_COLLECTION = "Launch_Properties"

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

    print(f"🚀 สแกนหาคิวงานอัปโหลดจาก '{SOURCE_COLLECTION}' (analyzed=True, uploaded=False)...")
    def pad_list(lst, size, default=0):
        """เติมค่า default ให้ลิสต์มีความยาวเท่ากับ size"""
        if not lst: return [default] * size
        return (lst + [default] * size)[:size]

    docs = fs.db.collection(SOURCE_COLLECTION).where(filter=FieldFilter("analyzed", "==", True)).where(filter=FieldFilter("uploaded", "==", False)).get()

    for doc in docs:
        prop_id = doc.id
        data = doc.to_dict()
        
        # Ensure color lists have exactly 14 elements
        room_colors = pad_list(data.get("room_color"), 14, 0)
        furniture_colors = pad_list(data.get("element_color"), 14, 0)
        
        # 1. Expand element_furniture from flattened string to List[List[str]]
        raw_furniture = pad_list(data.get("element_furniture"), 14, "")
        formatted_furniture = []
        for s in raw_furniture:
            if isinstance(s, str) and s.strip():
                items = [item.strip() for item in s.split(",") if item.strip()]
                formatted_furniture.append(items)
            else:
                formatted_furniture.append([])
        
        # 2. Determine dominant color Thai name using 70/30 weighting
        # (Room Color 70% / Furniture Color 30%)
        weighted_colors = []
        for i in range(14):
            # สูตร: (โครงสร้าง * 0.7) + (เฟอร์นิเจอร์ * 0.3)
            val = (room_colors[i] * 0.7) + (furniture_colors[i] * 0.3)
            weighted_colors.append(val)
            
        max_idx = weighted_colors.index(max(weighted_colors)) if any(weighted_colors) else 10
        dominant_color_thai = THAI_COLORS[max_idx]

        # 3. Handle structural elements (walls, floors, etc.)
        raw_room = pad_list(data.get("element_room"), 14, "")
        formatted_room = []
        for s in raw_room:
            if isinstance(s, str) and s.strip():
                items = [item.strip() for item in s.split(",") if item.strip()]
                formatted_room.append(items)
            else:
                formatted_room.append([])
                
        house_color = data.get("house_color", "ไม่ระบุ")
        house_color2 = data.get("house_color2", "")

        # 4. Construct Payload based on Staff API spec
        from datetime import datetime, timedelta
        # 🕒 ปรับให้เป็นเวลาไทย (UTC+7) เพื่อให้ Staff API แสดงผล "Just Now"
        now_thailand = datetime.utcnow() + timedelta(hours=7)
        now_iso = now_thailand.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        # จำกัดจำนวนไอเทมในลิสต์ ไม่ให้ยาวเกินที่ DB จะรับไหว (Max 5 items per color)
        safe_furniture = [items[:5] for items in formatted_furniture]
        safe_room = [items[:5] for items in formatted_room]

        payload = {
            "property_id": int(prop_id),
            "analyzed_at": now_iso, # 🕒 เพิ่มเวลาที่วิเคราะห์จริง
            "average_color_hex": "#FFFFFF", 
            "color": dominant_color_thai,
            "room_color": room_colors,
            "furniture_color": furniture_colors,
            "furniture_elements": safe_furniture,
            "house_color": house_color,
            "house_color2": house_color2,
            "room_elements": safe_room,
            "interior_style": data.get("architect_style", "Other"),
            "property_type": "house"
        }
        
        if api.submit_color_analysis(payload):
            fs.db.collection(SOURCE_COLLECTION).document(prop_id).update({
                "uploaded": True,
                "uploaded_at": time.time()
            })
            print(f"✅ Property {prop_id} Uploaded Successfully.")
        else:
            print(f"Failed to upload property {prop_id}.")
        
        # Add random delay to prevent 500 error
        import random
        delay = random.uniform(2.0, 4.0)
        print(f"Waiting {delay:.1f}s before next upload...")
        time.sleep(delay)

if __name__ == "__main__":
    upload_arnon_analysis()
