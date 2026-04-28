import os
import time
import requests
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# ⚙️ CONFIGURATION
SOURCE_COLLECTIONS = ["Launch_Properties"] 
PROJECT_LIMIT = None                  
TEST_PROPERTY_ID = None           
USE_STAGING = True                  

ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]

SYSTEM_COLOR_MAP = {
    "Green": "Green", "Brown": "Brown", "Red": "Red", "Dark Yellow": "Gold", "Orange": "Orange",
    "Purple": "Pink", "Pink": "Pink", "Light Yellow": "Yellow", "Yellowish Brown": "Cream",
    "Light Brown": "Cream", "White": "White", "Gray": "Gray", "Blue": "Blue", "Black": "Black"
}

THAI_COLORS_MAP = {
    "Green": "เขียว", "Brown": "น้ำตาล", "Red": "แดง", "Gold": "ทอง", "Orange": "ส้ม",
    "Pink": "ชมพู", "Yellow": "เหลือง", "Cream": "ครีม", "White": "ขาว", "Gray": "เทา",
    "Blue": "น้ำเงิน", "Black": "ดำ"
}

def recalculate_dominant_color_standard(data, room_w=0.5, furn_w=0.5):
    """
    คำนวณแบบมาตรฐาน 50/50 
    """
    # ใน Launch_Properties: room = 'room_color', furniture = 'element_color'
    room_comp = data.get("room_color", [0]*14)
    furn_comp = data.get("element_color", [0]*14)
    
    final_scores = []
    for i in range(14):
        score = (room_comp[i] * room_w) + (furn_comp[i] * furn_w)
        final_scores.append(score)

    mapped_scores = {}
    for i, score in enumerate(final_scores):
        eng_name = ENGLISH_COLORS[i]
        mapped_name = SYSTEM_COLOR_MAP.get(eng_name, eng_name)
        mapped_scores[mapped_name] = mapped_scores.get(mapped_name, 0) + score
        
    sorted_mapped = sorted(mapped_scores.items(), key=lambda x: x[1], reverse=True)
    dominant = sorted_mapped[0][0] if sorted_mapped else "White"
    return dominant

def list_to_color_dict(lst):
    if not lst or len(lst) < 14: return {color: 0 for color in ENGLISH_COLORS}
    return {ENGLISH_COLORS[i]: lst[i] for i in range(14)}

def upload_arnon_analysis():
    fs = FirestoreService()
    target_url = (os.getenv("AGENT_API_FALLBACK_URL") or "https://staging.yourhome.co.th") if USE_STAGING else "https://app.yourhome.co.th"
    base_url = target_url.rstrip('/')
    print(f"🛠️ MODE: {'[STAGING]' if USE_STAGING else '[PRODUCTION]'} -> {base_url}")

    # 🔐 AUTH
    login_payload = {"email": os.getenv("AGENT_API_EMAIL"), "password": os.getenv("AGENT_API_PASSWORD")}
    r_agent = requests.post(f"{base_url}/api/agent/login", json=login_payload, timeout=10)
    agent_headers = {"Authorization": f"Bearer {r_agent.json().get('data', {}).get('token')}", "Content-Type": "application/json"}
    
    staff_payload = {"email": os.getenv("STAFF_API_EMAIL"), "password": os.getenv("STAFF_API_PASSWORD")}
    r_staff_login = requests.post(f"{base_url}/api/staff/login", json=staff_payload, timeout=10)
    staff_headers = {"Authorization": f"Bearer {r_staff_login.json().get('data', {}).get('token')}", "Content-Type": "application/json"}
    print("✅ Auth Success (Agent & Staff).")

    for coll_name in SOURCE_COLLECTIONS:
        query = fs.db.collection(coll_name)
        docs = [query.document(TEST_PROPERTY_ID).get()] if TEST_PROPERTY_ID else query.where("true_color_analyzed", "==", True).limit(PROJECT_LIMIT).get()

        for p_doc in docs:
            if not p_doc.exists: continue
            prop_id = p_doc.id
            data = p_doc.to_dict()
            print(f"🏠 Processing Property: {prop_id} from {coll_name}")

            # บังคับคำนวณใหม่แบบ 50/50 ธรรมดา
            if coll_name == "Launch_Properties":
                house_color = recalculate_dominant_color_standard(data, 0.5, 0.5)
                print(f"      🔄 Recalculated (Standard 50/50) -> {house_color}")
                area_weight_payload = {"room": 50.0, "furniture": 50.0}
                room_list = data.get("room_color", [0]*14)
                furn_list = data.get("element_color", [0]*14)
            else:
                house_color = data.get("house_color", "White")
                area_weight_payload = data.get("area_weight")
                room_list = data.get("room_color_composition", [0]*14)
                furn_list = data.get("furniture_color_composition", [0]*14)

            dominant_thai = THAI_COLORS_MAP.get(house_color, "ขาว")
            room_color_dict = list_to_color_dict(room_list)
            furn_color_dict = list_to_color_dict(furn_list)
            
            # --- [UPDATE AGENT API] ---
            update_url = f"{base_url}/properties/{prop_id}/update" if "/api/agent" in base_url else f"{base_url}/api/agent/properties/{prop_id}/update"
            requests.post(update_url, headers=agent_headers, json={
                "house_color": house_color, "color": dominant_thai,
                "specifications": {
                    "style": data.get("architect_style", "Other"), 
                    "house_color": house_color, "color": dominant_thai,
                    "room_element_breakdown": data.get("room_element_breakdown", {}), 
                    "area_weight": area_weight_payload
                }
            }, timeout=10)
            print(f"      ✅ Agent API updated")

            # --- [SUBMIT STAFF API] ---
            from datetime import datetime, timedelta
            now_iso = (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            s_payload = {
                "property_id": int(prop_id), "analyzed_at": now_iso, "color": dominant_thai,
                "room_color": room_color_dict, "furniture_color": furn_color_dict,
                "furniture_elements": [[] for _ in range(14)], 
                "structural_colors": {k: list_to_color_dict(v) for k,v in data.get("structural_colors", {}).items()},
                "room_element_breakdown": data.get("room_element_breakdown", {}),
                "house_color": house_color, "interior_style": data.get("architect_style", "Other"), 
                "property_type": data.get("property_type", "house")
            }
            requests.post(f"{base_url}/api/staff/color-analyses", headers=staff_headers, json=s_payload, timeout=10)
            print(f"      ✅ Staff API upload success")

if __name__ == "__main__":
    upload_arnon_analysis()
