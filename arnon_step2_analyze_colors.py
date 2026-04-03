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

# ไม่ต้องระบุ START_ID/END_ID แล้ว เพราะจะดึงจาก Firestore โดยตรง

class PropertyAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    architect_style: str = Field(description="Strictly ONE of: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other. If Condo, use Interior Style. If House, use Exterior Architect Style.")
    room_color: List[int] = Field(description="Aggregated 14-color percentage for Walls and Doors in order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    element_color: List[int] = Field(description="Aggregated 14-color percentage for Furniture in the same order.")
    element_furniture: List[str] = Field(description="List of 14 strings. Each string 'i' contains comma-separated English names of furniture items in that exact color 'i'. If empty, use \"\". Max 10 items per color.")

def download_image(url: str, retries=1):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            img.thumbnail((800, 800))
            return img
        elif r.status_code == 403:
            print(f"      [!] 403 Forbidden: รูปภาพถูกลบหรือปิดกั้นทื่ต้นทาง S3")
        else:
            print(f"      [!] Download failed: Status {r.status_code}")
    except Exception as e:
        print(f"      [!] Download error: {e}")
    return None

def analyze_arnon_properties():
    # อัปเกรดรุ่นโมเดลตามคำสั่งบอส (เพื่อความละเอียด)
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
    print("🚀 เริ่มดึงข้อมูลคิวงานวิเคราะห์สีจาก 'Launch_Properties' (analyzed=False/None)...")
    docs = fs.db.collection("Launch_Properties").get()
    
    tasks = []
    for doc in docs:
        d = doc.to_dict()
        # 🔥 งานที่ต้องทำคือ analyzed เป็น False หรือเป็น None (ยังไม่เคยมีผลสี)
        if not d.get("analyzed") and not d.get("room_color"):
             tasks.append(doc)
    
    print(f"📊 Found {len(tasks)} tasks to analyze.")
    
    for doc in tasks:
        prop_id = doc.id
        data = doc.to_dict()
        images_info = data.get("images", [])
        
        if not images_info:
            print(f"⚠️ Skip {prop_id}: ไม่มีข้อมูลรูปภาพ")
            continue

        # 🕵️‍♂️ กรองเอาทุกภาพยกเว้นภาพที่เป็น "Common facilities" เพื่อให้ AI เห็นห้องต่างๆ ครบถ้วน
        gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]
        
        if not gallery_images:
            print(f"⚠️ Skip {prop_id}: ไม่มีภาพ gallery ให้วิเคราะห์")
            continue

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
            
        # 📸 ดาวน์โหลดรูปทื่ Refresh แล้ว (จำกัดแค่ 15 รูปทิเด่นๆ)
        pil_images = []
        for img_meta in gallery_images[:15]:
            img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("url")
            pil_img = download_image(img_url)
            if pil_img:
                pil_images.append(pil_img)
        
        if not pil_images:
            print(f"❌ Property {prop_id}: ไม่สามารถโหลดรูปภาพได้เลย")
            continue

        print(f"🎬 Analyzing Property {prop_id} with {len(pil_images)} images...")

        # ดึง Property Type จาก Agent API สดๆ
        headers = api._get_auth_headers()
        base_url = api.base_url.rstrip('/')
        prop_type_name = "Unknown"
        is_condo = False
        
        try:
            r_detail = requests.get(f"{base_url}/api/agent/properties/{prop_id}", headers=headers, timeout=10)
            if r_detail.status_code == 200:
                p_data = r_detail.json().get("data", {})
                prop_type_name = str(p_data.get("property_type", {}).get("name", "")).strip()
                if "condo" in prop_type_name.lower() or "apartment" in prop_type_name.lower():
                    is_condo = True
        except Exception as e:
            print(f"      [!] Failed to check property_type: {e}")

        # ปรับกติกาย่อย (Dynamic Style Criteria)
        if is_condo:
            style_instruction = "This is a CONDO/APARTMENT. Identify the INTERIOR DECORATION style based on the room arrangement and furniture."
        else:
            style_instruction = f"This is a {prop_type_name or 'HOUSE/BUILDING'}. Identify the ARCHITECTURAL exterior style based on the building shape and structure."

        prompt = (
            "Analyze these images of a SINGLE property to summarize its characteristics. "
            "IMPORTANT: Images show the same rooms and furniture from DIFFERENT angles. DO NOT double-count items. "
            "1. Mental Mapping: Build a mental spatial map of the property. Identify unique furniture items (e.g., if you see the same blue bed in 3 photos, it counts as ONE blue bed).\n"
            f"2. {style_instruction} You MUST choose EXACTLY ONE from this list: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
            "3. 'room_color': Aggregate percentage (0-100) for Walls and Doors surfaces based on the estimated total surface area of the entire property.\n"
            "4. 'element_color': Aggregate percentage (0-100) for Furniture surface area. Deduplicate objects across images to prevent color inflation.\n"
            "5. Color order (14 colors): [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
            "6. Both color arrays must be exactly 14 integers summing to exactly 100.\n"
            "7. 'element_furniture': Array of exactly 14 STRINGS. Each string 'i' contains unique comma-separated furniture names in that color 'i'.\n"
            "8. STRICTLY EXCLUDE all electrical appliances (AC, washing machines, refrigerators, TVs, microwaves, etc.).\n"
            "9. COHERENCE RULE (CRITICAL): If 'element_furniture[i]' is NOT empty, 'element_color[i]' MUST be > 0. If 'element_color[i]' is 0, 'element_furniture[i]' MUST be \"\".\n"
            "10. NO REPETITION & LIMIT: List at most 10 unique items per color string. DO NOT repeat the same word. Use plural (e.g., 'chairs') instead of repeating same text."
        )
        
        # --- Gemini Analysis with Retry Logic ---
        success = False
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # ส่งรูปยกชุดให้ AI
                contents = [prompt] + pil_images
                response = client.models.generate_content(
                    model=model_name,
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
                
                # บันทึกผลลัพธ์ที่ระดับ Property
                fs.db.collection("Launch_Properties").document(prop_id).update({
                    "architect_style": res.architect_style,
                    "room_color": res.room_color,
                    "element_color": res.element_color,
                    "element_furniture": res.element_furniture,
                    "analyzed": True,
                    "analyzed_at": now_iso, # 🕒 บันทึกเวลาไทยลง Firestore
                    "uploaded": False,
                    "images_analyzed": len(pil_images)
                })
                print(f"✅ Property {prop_id} Sync Success!")
                success = True
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
