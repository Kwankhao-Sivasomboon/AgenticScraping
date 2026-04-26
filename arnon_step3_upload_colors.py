import os
import time
import requests
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# ⚙️ ตั้งค่าคอลเลกชันที่ต้องการดึงข้อมูล
SOURCE_COLLECTIONS = ["Launch_Properties", "arnon_properties"]
PROJECT_LIMIT = 500  # ปรับเพิ่มได้ตามต้องการ

# Predefined 14 colors in Thai
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู", 
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

def pad_list(lst, size, default=0):
    """เติมค่า default ให้ลิสต์มีความยาวเท่ากับ size"""
    if not lst: return [default] * size
    return (lst + [default] * size)[:size]

def upload_arnon_analysis():
    fs = FirestoreService()
    api = APIService()
    
    # 🔑 Authenticate ทั้ง Agent และ Staff
    if not api.authenticate():
        print("❌ Agent Authentication failed.")
        return
        
    if not api.authenticate_staff():
        print("❌ Staff Authentication failed. Please check STAFF_API_EMAIL in .env")
        return

    for coll_name in SOURCE_COLLECTIONS:
        print(f"\n🚀 Scanning collection '{coll_name}' (analyzed=True, uploaded=False)...")
        docs = fs.db.collection(coll_name).where("analyzed", "==", True).where("uploaded", "==", False).limit(PROJECT_LIMIT).stream()

        for doc in docs:
            prop_id = doc.id
            data = doc.to_dict()
            print(f"🏠 Processing Property: {prop_id}")
            
            # Ensure color lists have exactly 14 elements
            room_colors = pad_list(data.get("room_color"), 14, 0)
            furniture_colors = pad_list(data.get("element_color"), 14, 0)
            
            # 1. Expand element_furniture
            raw_furniture = pad_list(data.get("element_furniture"), 14, "")
            formatted_furniture = []
            for s in raw_furniture:
                if isinstance(s, str) and s.strip():
                    items = [item.strip() for item in s.split(",") if item.strip()]
                    formatted_furniture.append(items)
                else:
                    formatted_furniture.append([])
            
            # 2. Determine dominant color Thai name using 76/24 weighting
            weighted_colors = []
            for i in range(14):
                val = (room_colors[i] * 0.76) + (furniture_colors[i] * 0.24)
                weighted_colors.append(val)
                
            max_idx = weighted_colors.index(max(weighted_colors)) if any(weighted_colors) else 10
            dominant_color_thai = THAI_COLORS[max_idx]

            # 3. Handle structural elements
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

            # --- [4] Check Owner & Update Agent API ---
            headers = api._get_auth_headers()
            base_url = api.base_url.rstrip('/')
            is_arnon_fallback = False
            is_arnon_owner = False
            existing_specs = {}

            try:
                r_detail = requests.get(f"{base_url}/api/agent/properties/{prop_id}", headers=headers, timeout=10)
                if r_detail.status_code == 200:
                    p_data = r_detail.json().get("data", {})
                    owner_email = p_data.get("owner", {}).get("email", "").lower()
                    arnon_email_env = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
                    is_arnon_owner = (owner_email == arnon_email_env)
                    
                    if is_arnon_owner:
                        print(f"      🎯 Arnon Property. Switching account...")
                        api.authenticate(use_arnon=True)
                        is_arnon_fallback = True
                    
                    raw_specs = p_data.get("specifications", {}) or p_data.get("specs", {})
                    if isinstance(raw_specs, dict): existing_specs = raw_specs

                # 🛠️ Update Agent API
                specs_payload = {
                    "style": data.get("architect_style", "Other"),
                    "house_color": house_color,
                    "color": dominant_color_thai
                }
                for k in ["floors", "bedrooms", "bathrooms"]:
                    if existing_specs.get(k): specs_payload[k] = existing_specs[k]

                agent_payload = {
                    "house_color": house_color,
                    "color": dominant_color_thai,
                    "specifications": specs_payload,
                    "specs": specs_payload
                }
                
                update_api = api
                if is_arnon_owner and not is_arnon_fallback:
                    update_api = APIService()
                    update_api.authenticate(use_arnon=True)
                
                if update_api.update_property(prop_id, agent_payload):
                    print(f"      ✅ Agent API updated")
                else:
                    print(f"      ❌ Agent API update failed")

            except Exception as e:
                print(f"      [!] Error Agent API: {e}")

            # --- [5] Submit to Staff API ---
            from datetime import datetime, timedelta
            now_thailand = datetime.utcnow() + timedelta(hours=7)
            now_iso = now_thailand.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

            payload = {
                "property_id": int(prop_id),
                "analyzed_at": now_iso,
                "average_color_hex": "#FFFFFF", 
                "color": dominant_color_thai,
                "room_color": room_colors,
                "furniture_color": furniture_colors,
                "furniture_elements": [items[:5] for items in formatted_furniture],
                "house_color": house_color,
                "house_color2": house_color2,
                "room_elements": [items[:5] for items in formatted_room],
                "interior_style": data.get("architect_style", "Other"),
                "property_type": "house"
            }
            
            if api.submit_color_analysis(payload):
                fs.db.collection(coll_name).document(prop_id).update({
                    "uploaded": True,
                    "uploaded_at": time.time()
                })
                print(f"✅ Staff API upload success")
            else:
                print(f"❌ Staff API upload failed")
            
            if is_arnon_fallback: api.authenticate(use_arnon=False)
            time.sleep(1.5)

if __name__ == "__main__":
    upload_arnon_analysis()
