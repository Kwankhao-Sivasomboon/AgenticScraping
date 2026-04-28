import os
import time
import requests
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# ⚙️ CONFIGURATION
SOURCE_COLLECTIONS = ["area_color"] 
PROJECT_LIMIT = None                  
TEST_PROPERTY_ID = None           
USE_STAGING = False 

ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]

# 🔄 SYSTEM_COLOR_MAP (Commented out for future use)
# SYSTEM_COLOR_MAP = {
#     "Green": "Green", "Brown": "Brown", "Red": "Red", "Dark Yellow": "Yellow", "Orange": "Orange",
#     "Purple": "Pink", "Pink": "Pink", "Light Yellow": "Cream", "Yellowish Brown": "Cream",
#     "Light Brown": "Cream", "White": "White", "Gray": "Gray", "Blue": "Blue", "Black": "Black"
# }

THAI_COLORS_MAP = {
    "Green": "เขียว", "Brown": "น้ำตาล", "Red": "แดง", 
    "Dark Yellow": "เหลืองเข้ม", "Orange": "ส้ม", "Purple": "ม่วง", "Pink": "ชมพู",
    "Light Yellow": "เหลืองอ่อน", "Yellowish Brown": "น้ำตาลอมเหลือง", "Light Brown": "น้ำตาลอ่อน",
    "White": "ขาว", "Gray": "เทา", "Blue": "น้ำเงิน", "Black": "ดำ"
}

def get_dominant_color_logic(room_list, furn_list, room_w, furn_w):
    """
    ลอจิกเดียวกับใน arnon_compare_colors_report.py
    คำนวณสีเด่นจาก room และ furniture โดยไม่มีการ Map สี และไม่มีตัวคูณพิเศษ
    """
    if not room_list or len(room_list) < 14: room_list = [0] * 14
    if not furn_list or len(furn_list) < 14: furn_list = [0] * 14

    scores = {}
    for i in range(14):
        score = (room_list[i] * room_w) + (furn_list[i] * furn_w)
        color_name = ENGLISH_COLORS[i]
        scores[color_name] = scores.get(color_name, 0) + score

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    dominant = sorted_scores[0][0] if sorted_scores else "White"
    return dominant

def list_to_color_dict(lst):
    if not lst or len(lst) < 14: return {color: 0 for color in ENGLISH_COLORS}
    return {ENGLISH_COLORS[i]: lst[i] for i in range(14)}

def upload_production_sync():
    fs = FirestoreService()
    target_url = "https://app.yourhome.co.th" if not USE_STAGING else "https://staging.yourhome.co.th"
    base_url = target_url.rstrip('/')
    print(f"🚀 PRODUCTION SYNC (REPORT LOGIC): {base_url}")

    # 🔐 AUTH
    login_payload = {"email": os.getenv("AGENT_API_EMAIL"), "password": os.getenv("AGENT_API_PASSWORD")}
    r_agent = requests.post(f"{base_url}/api/agent/login", json=login_payload, timeout=10)
    if r_agent.status_code != 200: return print("❌ Agent Login Failed")
    agent_headers = {"Authorization": f"Bearer {r_agent.json().get('data', {}).get('token')}", "Content-Type": "application/json"}
    
    staff_payload = {"email": os.getenv("STAFF_API_EMAIL"), "password": os.getenv("STAFF_API_PASSWORD")}
    r_staff_login = requests.post(f"{base_url}/api/staff/login", json=staff_payload, timeout=10)
    if r_staff_login.status_code != 200: return print("❌ Staff Login Failed")
    staff_headers = {"Authorization": f"Bearer {r_staff_login.json().get('data', {}).get('token')}", "Content-Type": "application/json"}
    print("✅ Auth Success.")

    for coll_name in SOURCE_COLLECTIONS:
        print(f"🔍 Scanning {coll_name} for analyzed properties...")
        query = fs.db.collection(coll_name).where("true_color_analyzed", "==", True)
        docs = query.get()

        for ac_doc in docs:
            prop_id = ac_doc.id
            ac_data = ac_doc.to_dict()

            lp_doc = fs.db.collection("Launch_Properties").document(prop_id).get()
            if not lp_doc.exists: continue
            lp_data = lp_doc.to_dict()

            # 🛠️ ดึงข้อมูลและน้ำหนัก
            room_list = lp_data.get("room_color", [0]*14)
            furn_list = lp_data.get("element_color", [0]*14)
            area_weight = ac_data.get("area_weight", {"room": 50.0, "furniture": 50.0})
            room_w = area_weight.get("room", 50.0) / 100
            furn_w = area_weight.get("furniture", 50.0) / 100

            # 🔄 คำนวณด้วยลอจิกเดียวกับ Report
            house_color = get_dominant_color_logic(room_list, furn_list, room_w, furn_w)
            dominant_thai = THAI_COLORS_MAP.get(house_color, "ขาว")
            
            print(f"🏠 Property {prop_id}: {house_color} (R:{room_w*100} F:{furn_w*100})")

            # เตรียมข้อมูลสำหรับ API
            room_color_dict = list_to_color_dict(room_list)
            furn_color_dict = list_to_color_dict(furn_list)
            formatted_struct = {k: list_to_color_dict(v) for k,v in lp_data.get("structural_colors", {}).items()}

            # --- [UPDATE AGENT API] ---
            update_url = f"{base_url}/api/agent/properties/{prop_id}/update"
            requests.post(update_url, headers=agent_headers, json={
                "house_color": house_color, "color": dominant_thai,
                "specifications": {
                    "style": lp_data.get("architect_style", "Other"), 
                    "house_color": house_color, "color": dominant_thai,
                    "room_element_breakdown": lp_data.get("room_element_breakdown", {}), 
                    "area_weight": area_weight
                }
            }, timeout=10)

            # --- [SUBMIT STAFF API] ---
            from datetime import datetime, timedelta
            now_iso = (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            s_payload = {
                "property_id": int(prop_id), "analyzed_at": now_iso, "color": dominant_thai,
                "room_color": room_color_dict, "furniture_color": furn_color_dict,
                "furniture_elements": [[] for _ in range(14)], 
                "structural_colors": formatted_struct,
                "room_element_breakdown": lp_data.get("room_element_breakdown", {}),
                "house_color": house_color, "interior_style": lp_data.get("architect_style", "Other"), 
                "property_type": lp_data.get("property_type", "house")
            }
            requests.post(f"{base_url}/api/staff/color-analyses", headers=staff_headers, json=s_payload, timeout=10)

if __name__ == "__main__":
    upload_production_sync()
