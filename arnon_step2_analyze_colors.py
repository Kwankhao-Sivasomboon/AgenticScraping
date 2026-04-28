import os
import time
from io import BytesIO
import requests
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ConfigDict
from typing import List
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

# ⚙️ ตั้งค่าคอลเลกชันที่ต้องการบันทึกข้อมูล
TARGET_COLLECTION = "Launch_Properties"
SECONDARY_COLLECTION = "arnon_properties" # สำหรับงานที่เป็นของคุณอานนท์ (Fallback)

# English mapping for the 14 colors
ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink", 
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]

# System Base Colors (14)
SYSTEM_COLOR_MAP = {
    "Green": "Green",
    "Brown": "Brown",
    "Red": "Red",
    "Dark Yellow": "Yellow",
    "Orange": "Orange",
    "Purple": "Pink",
    "Pink": "Pink",
    "Light Yellow": "Cream",
    "Yellowish Brown": "Cream",
    "Light Brown": "Cream",
    "White": "White",
    "Gray": "Gray",
    "Blue": "Blue",
    "Black": "Black"
}

SYSTEM_THAI_MAP = {
    "Black": "ดำ", "Blue": "น้ำเงิน", "Brown": "น้ำตาล", "Cream": "ครีม",
    "Gold": "ทอง", "Gray": "เทา", "Green": "เขียว", "Light Gray": "เทาอ่อน",
    "Orange": "ส้ม", "Pink": "ชมพู", "Red": "แดง", "Silver": "เงิน",
    "White": "ขาว", "Yellow": "เหลือง"
}

class PropertyAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    architect_style: str = Field(description="Strictly ONE of: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.")
    poor_condition_image_indices: List[int] = Field(default_factory=list, description="Indices of images showing old/dirty condition.")
    raw_room_color: str = Field(description="Detailed raw colors. FORMAT exactly as: 'Walls: [color], Doors: [color], Floors: [color], Ceilings: [color]'")
    raw_furniture_color: str = Field(description="Detailed raw colors for various furniture elements (e.g., 'Sofa: Navy Blue, Bed: Oak Wood, Table: White')")
    # ... (the rest remains compatible)
    room_color: List[int] = Field(description="Aggregated 14-color percentage for structural elements (Walls, Doors, Floors, Ceilings/Roofs) in order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    element_room: List[str] = Field(description="List of 14 strings. Each string 'i' contains comma-separated English names of structural elements (e.g. wall, door, floor, ceiling, roof) in that exact color 'i'. If empty, use \"\". Max 10 items per color.")
    element_color: List[int] = Field(description="Aggregated 14-color percentage for Furniture in the same order.")
    element_furniture: List[str] = Field(description="List of 14 strings. Each string 'i' contains unique comma-separated furniture names in that color 'i'. If empty, use \"\". Max 10 items per color.")

def download_image_as_part(url: str, agent_token: str = None, base_url: str = None):
    if not url: return None, None
    original_url = url
    headers = {"User-Agent": "Mozilla/5.0"}
    if agent_token: headers["Authorization"] = f"Bearer {agent_token}"
    
    # Handle relative URLs
    if not url.startswith(('http://', 'https://')):
        if base_url:
            clean_base = base_url.rstrip('/')
            if clean_base.endswith('/api'): clean_base = clean_base[:-4]
            url = f"{clean_base}/{url.lstrip('/')}"
        else: return None, None

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            if img.mode != 'RGB': img = img.convert('RGB')
            img.thumbnail((512, 512))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=80) 
            return types.Part.from_bytes(data=buffer.getvalue(), mime_type='image/jpeg'), 200
        elif r.status_code == 404 and "/storage/" not in url and base_url:
            # Retry with /storage/
            clean_base = base_url.rstrip('/')
            if clean_base.endswith('/api'): clean_base = clean_base[:-4]
            fallback_url = f"{clean_base}/storage/{original_url.lstrip('/')}"
            r2 = requests.get(fallback_url, headers=headers, timeout=15)
            if r2.status_code == 200:
                img = Image.open(BytesIO(r2.content))
                if img.mode != 'RGB': img = img.convert('RGB')
                img.thumbnail((512, 512))
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=80)
                return types.Part.from_bytes(data=buffer.getvalue(), mime_type='image/jpeg'), 200
        return None, r.status_code
    except Exception as e:
        return None, 999

def analyze_arnon_properties():
    # 🚀 กลับมาใช้ Gemini 2.5 Flash เพื่อความเสถียร (รุ่น 3 Preview ดูเหมือนจะทำให้เกิดอาการค้างในบางช่วง)
    model_name = 'gemini-2.5-flash'
    api_key = os.getenv('GEMINI_API_KEY_COLOR') or os.getenv('GEMINI_API_KEY')
    if not api_key:
        print(" Gemini API Key not found.")
        return
        
    client = genai.Client(api_key=api_key)
    fs = FirestoreService()
    
    # 🚀 ปล่อยให้ APIService เลือก Email/Password จาก .env เองตามลำดับความสำคัญ
    api = APIService()
    api.authenticate()
    
    # ดึงทั้งหมดที่ยังไม่ได้วิเคราะห์ (analyzed == False) หรือยังไม่มีฟิลด์ analyzed เลย
    print(f"🚀 เริ่มดึงข้อมูลคิวงานวิเคราะห์สีจาก '{TARGET_COLLECTION}' (analyzed=False/None)...")
    docs = fs.db.collection(TARGET_COLLECTION).get()
    
    tasks = []
    total_docs = 0
    analyzed_count = 0
    for doc in docs:
        total_docs += 1
        d = doc.to_dict()
        # 🔥 งานที่ต้องทำคือ analyzed เป็น False หรือเป็น None (เอาเช็ค room_color ออกเพื่อให้เจอครบ 888 ตามบอสสั่ง)
        if not d.get("analyzed"):
             tasks.append(doc)
        else:
             analyzed_count += 1
    
    print(f"📊 Total Docs in {TARGET_COLLECTION}: {total_docs}")
    print(f"✅ Already Analyzed: {analyzed_count}")
    print(f"🎯 Tasks remaining to analyze: {len(tasks)}")
    
    for doc in tasks:
        prop_id = doc.id
        data = doc.to_dict()
        fetch_email = data.get("fetch_email")
        
        # 🚩 เช็คและสลับบัญชีให้ตรงกับ fetch_email
        if fetch_email and api.email != fetch_email:
            print(f"🔄 Switching account: {api.email} -> {fetch_email}")
            use_arnon = (fetch_email == os.getenv("AGENT_ARNON_EMAIL"))
            if not api.authenticate(use_arnon=use_arnon):
                print(f"❌ Failed to switch to {fetch_email}. Skipping...")
                continue
        
        # เช็คว่าเคยรันไปหรือยัง
        if data.get("analyzed") is True:
            print(f"⏭️ Skip {prop_id}: Already analyzed")
            continue

        print(f"\n🏠 Processing Property: {prop_id} (Account: {api.email})")
        images_info = data.get("images", [])
        
        if not images_info:
            print(f"⚠️ Skip {prop_id}: ไม่มีข้อมูลรูปภาพ")
            continue

        # 🕵️‍♂️ กรองเอาทุกภาพยกเว้นภาพที่เป็น "Common facilities" เพื่อให้ AI เห็นห้องต่างๆ ครบถ้วน
        gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]
        
        if not gallery_images:
            print(f"⚠️ Skip {prop_id}: ไม่มีภาพ gallery ให้วิเคราะห์")
            continue

        # ------------------------------------------------------
        # 1. Check Property Detail & Owner BEFORE anything else
        # ------------------------------------------------------
        headers = api._get_auth_headers()
        base_url = api.base_url.rstrip('/')
        prop_type_name = "Unknown"
        is_condo = False
        is_arnon_fallback = False
        
        try:
            r_detail = requests.get(f"{base_url}/api/agent/properties/{prop_id}", headers=headers, timeout=10)
            if r_detail.status_code == 200:
                p_data = r_detail.json().get("data", {})
                
                # 🕵️‍♂️ Check Owner: ถ้าเป็นของอานนท์ ให้สลับไปใช้บัญชีอานนท์ทันที
                owner_email = p_data.get("owner", {}).get("email", "").lower()
                arnon_email_env = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
                
                if owner_email == arnon_email_env:
                    print(f"      🎯 Property owner is Arnon ({owner_email}). Switching to Arnon account...")
                    if api.authenticate(use_arnon=True):
                        is_arnon_fallback = True
                        headers = api._get_auth_headers() # Update headers
                    else:
                        print("      ❌ Failed to switch to Arnon account.")

                prop_type_name = str(p_data.get("property_type", {}).get("name", "")).strip()
                is_arnon_owner = (owner_email == arnon_email_env)
                if "condo" in prop_type_name.lower() or "apartment" in prop_type_name.lower():
                    is_condo = True
        except Exception as e:
            print(f"      [!] Failed to check property_type/owner: {e}")

        # ------------------------------------------------------
        # 2. Refresh URLs & Download Images (using correct account)
        # ------------------------------------------------------
        # 🔄 Refresh URLs (Batch)
        img_ids = [img.get("id") for img in gallery_images if img.get("id")]
        print(f"🔄 Refreshing Signed URLs for {len(img_ids)} images...")
        refreshed = api.refresh_photo_urls(img_ids)
        
        # จัดการ URL ใหม่
        url_map = {}
        if refreshed and isinstance(refreshed, dict):
            if "refreshed_images" in refreshed:
                items = refreshed.get("refreshed_images", [])
            else:
                items = refreshed.get("data", {}).get("refreshed_images", [])
                
            for item in items:
                url_map[str(item.get("id"))] = item.get("url")
            
        # 📸 ดาวน์โหลดรูป
        image_parts = []
        original_image_ids = []
        
        for img_meta in gallery_images[:15]:
            img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("validated_url") or img_meta.get("url")
            part, status = download_image_as_part(img_url, agent_token=api.token, base_url=api.base_url)
            
            # Fallback เผื่อเจอ 403 แบบไม่คาดคิด (กรณีอื่นๆ)
            if status == 403 and not is_arnon_fallback:
                print(f"      ⚠️ Unexpected 403. Attempting fallback to Arnon account...")
                if api.authenticate(use_arnon=True):
                    is_arnon_fallback = True
                    part, status = download_image_as_part(img_url, agent_token=api.token, base_url=api.base_url)

            if part:
                image_parts.append(part)
                original_image_ids.append(str(img_meta.get("id")))
        
        if not image_parts:
            print(f"❌ Property {prop_id}: ไม่สามารถโหลดรูปภาพได้เลย")
            if is_arnon_fallback: api.authenticate(use_arnon=False)
            continue

        # กำหนดคอลเลกชันปลายทาง
        final_collection = SECONDARY_COLLECTION if is_arnon_fallback else TARGET_COLLECTION
        print(f"      📥 Will save results to: '{final_collection}'")

        # ปรับกติกาย่อย (Dynamic Style Criteria)
        if is_condo:
            style_instruction = "This is a CONDO/APARTMENT. Identify the INTERIOR DECORATION style based on the room arrangement and furniture."
        else:
            style_instruction = f"This is a {prop_type_name or 'HOUSE/BUILDING'}. Identify the ARCHITECTURAL exterior style based on the building shape and structure."

        prompt = (
            "Analyze these images of a SINGLE property to summarize its characteristics. The images are provided in a sequential list (Order: 0, 1, 2, ...).\n"
            "IMPORTANT: Images show the same rooms and furniture from DIFFERENT angles. DO NOT double-count items. "
            "1. Mental Mapping: Build a mental spatial map of the property. Identify unique furniture items (e.g., if you see the same blue bed in 3 photos, it counts as ONE blue bed).\n"
            "   - 'poor_condition_image_indices': Identify images showing SEVERE structural damage, highly unsanitary/dirty conditions, or extreme hoarding/clutter. DO NOT flag normal empty rooms, slightly older properties, or average lived-in spaces. BE EXTREMELY CONSERVATIVE. If in doubt, return [].\n"
            f"2. {style_instruction} You MUST choose EXACTLY ONE from this list: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
            "3. 'raw_room_color': Provide detailed raw colors. Format exactly as: 'Walls: [color], Doors: [color], Floors: [color], Ceilings: [color]'.\n"
            "4. 'raw_furniture_color': Provide the true/raw colors of the furniture in a single string (e.g. 'Sofa: Emerald Green, Bed: Walnut').\n"
            "5. 'room_color': Aggregate percentage (0-100) for ALL structural elements (Walls, Doors, Floors, Ceilings).\n"
            "6. 'element_room': Array of 14 strings. Each string 'i' contains ONLY elements from this strict list ['wall', 'door', 'floor', 'ceiling'] that appear in color index 'i'. DO NOT include any other words (no 'roof', no 'window', etc).\n"
            "7. 'element_color': Aggregate percentage (0-100) for Furniture.\n"
            "8. 'element_furniture': Array of 14 strings listing unique furniture items in each color index.\n"
            "9. Color order (14 colors): [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
            "10. Both color arrays must be exactly 14 integers summing to exactly 100.\n"
            "11. STRICTLY EXCLUDE all electrical appliances (AC, washing machines, refrigerators, TVs, microwaves, etc.).\n"
            "12. COHERENCE RULE (CRITICAL): If 'element_furniture[i]' is NOT empty, 'element_color[i]' MUST be > 0. If 'element_color[i]' is 0, 'element_furniture[i]' MUST be \"\".\n"
            "13. NO REPETITION & LIMIT: List at most 10 unique items per color string. DO NOT repeat the same word. Use plural (e.g., 'chairs') instead of repeating same text.\n"
            "14. LIGHTING COMPENSATION: Photos often have warm yellow/orange lighting that can make White walls look Pink or Orange. Identify the ACTUAL material color as a human would see it in neutral daylight.\n"
            "15. STRICTLY EXCLUDE nature, trees, plants, grass, and garden elements. Focus ONLY on the Building Facade and Man-made materials.\n"
            "16. TONE PRIORITY: If a color is ambiguous between a warm tone (Cream, Beige, Light Brown) and a cool tone (Gray, White), PRIORITIZE the warm tone."
        )
        
        # --- Gemini Analysis with Retry Logic ---
        success = False
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 🕒 Pacing เล็กน้อยก่อนส่ง AI
                time.sleep(3)
                print(f"🎬 Analyzing Property {prop_id} with {len(image_parts)} images...")

                # ส่งรูป (ที่บีบอัดแล้ว) ยกชุดให้ AI 
                contents = [prompt] + image_parts
                # ใช้ gemini-2.5-flash เป็นตัวหลัก
                current_model = "gemini-2.5-flash" if attempt < 2 else "gemini-3.1-flash-lite-preview"
                response = client.models.generate_content(
                    model=current_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=PropertyAnalysis,
                        temperature=0.1
                    )
                )
                res = response.parsed
                
                from datetime import datetime, timedelta
                now_iso = (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
                
                # คำนวณ house_color (อันดับ 1) และ house_color2 (อันดับ 2)
                # 🏠 สูตรใหม่: เน้นสีโครงสร้าง 76% และลดน้ำหนักเฟอร์นิเจอร์เหลือ 24%
                combined_colors = []
                for i in range(14):
                    r_val = res.room_color[i] if i < len(res.room_color) else 0
                    e_val = res.element_color[i] if i < len(res.element_color) else 0
                    combined_colors.append((r_val * 0.76) + (e_val * 0.24))
                    
                # Aggregate into System Colors
                system_scores = {c: 0.0 for c in set(SYSTEM_COLOR_MAP.values())}
                for i in range(14):
                    ai_color = ENGLISH_COLORS[i]
                    sys_color = SYSTEM_COLOR_MAP[ai_color]
                    system_scores[sys_color] += combined_colors[i]
                
                sorted_sys_colors = sorted(system_scores.items(), key=lambda x: x[1], reverse=True)
                house_color = sorted_sys_colors[0][0] if sorted_sys_colors[0][1] > 0 else "Not Specified"
                house_color2 = sorted_sys_colors[1][0] if len(sorted_sys_colors) > 1 and sorted_sys_colors[1][1] > 0 else ""

                # แมป Index ภาพที่เก่า/สกปรก กลับไปเป็น Image ID
                poor_image_ids = []
                for idx in res.poor_condition_image_indices:
                    if 0 <= idx < len(original_image_ids):
                        poor_image_ids.append(original_image_ids[idx])

                # บันทึกผลลัพธ์ที่ระดับ Property
                update_payload = {
                    "raw_room_color": res.raw_room_color,
                    "raw_furniture_color": res.raw_furniture_color,
                    "architect_style": res.architect_style,
                    "room_color": res.room_color,
                    "element_room": res.element_room,
                    "house_color": house_color,
                    "house_color2": house_color2,
                    "element_color": res.element_color,
                    "element_furniture": res.element_furniture,
                    "analyzed": True,
                    "analyzed_at": now_iso,
                    "uploaded": False,
                    "images_analyzed": len(image_parts)
                }

                # ⚠️ เฉพาะถ้าเจอภาพรก/สกปรก ถึงจะอัปเดตฟิลด์นี้ (ตามที่บอสถาม)
                if poor_image_ids:
                    update_payload["poor_condition_image_ids"] = poor_image_ids

                fs.db.collection(final_collection).document(prop_id).set(update_payload, merge=True)
                
                # ถ้าบันทึกลง collection ใหม่ ต้องปักธง analyzed ใน collection หลักด้วย (ถ้ามี)
                if final_collection != TARGET_COLLECTION:
                    fs.db.collection(TARGET_COLLECTION).document(prop_id).update({"analyzed": True, "moved_to_arnon": True})
                
                
                print(f"✅ Property {prop_id} Sync Success!")
                success = True
                # Reset กลับเป็น Primary เพื่อเริ่มงานชิ้นใหม่ด้วยสิทธิ์ปกติ (เว้นแต่คุณต้องการให้ค้าง Arnon ไว้)
                if is_arnon_fallback: api.authenticate(use_arnon=False)
                time.sleep(2)
                break # Success! หลุดจาก retry loop
                
            except Exception as e:
                err_msg = str(e)
                if ("503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 10
                    print(f"⚠️ Gemini Overloaded (503/429) for {prop_id}: Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Gemini Error for {prop_id}: {e}")
                    time.sleep(4)
                    break

if __name__ == "__main__":
    analyze_arnon_properties()
