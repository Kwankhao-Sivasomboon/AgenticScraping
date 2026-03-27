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
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()

class PropertyAnalysis(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    architect_style: str = Field(description="Dominant Architectural or Interior style: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other")
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
    
    # Login Arnon
    arnon_email = os.getenv('AGENT_ARNON_EMAIL')
    arnon_pass = os.getenv('AGENT_ARNON_PASSWORD')
    api = APIService(email=arnon_email, password=arnon_pass)
    api.authenticate()
    
    # ดึงทั้งหมด (Analyzed ทั้ง True และ False) มาดามใหม่ด้วย Flash ตัวเต็ม
    docs = list(fs.db.collection("ARNON_properties").stream())
    
    if not docs:
        print(" ไม่มีข้อมูลในระบบเลยครับ!")
        return

    print(f" เริ่มวิเคราห์ 'ทั้งหมด' (Re-processing): {len(docs)} properties...")

    for doc in docs:
        prop_id = doc.id
        data = doc.to_dict()
        images_info = data.get("images", [])
        
        if not images_info:
            print(f"⚠️ Skip {prop_id}: ไม่มีข้อมูลรูปภาพ")
            continue

        # 🔄 Refresh URLs (Batch)
        img_ids = [img.get("id") for img in images_info if img.get("id")]
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
        for img_meta in images_info[:15]:
            img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("url")
            pil_img = download_image(img_url)
            if pil_img:
                pil_images.append(pil_img)
        
        if not pil_images:
            print(f"❌ Property {prop_id}: ไม่สามารถโหลดรูปภาพได้เลย")
            continue

        print(f"🎬 Analyzing Property {prop_id} with {len(pil_images)} images...")

        prompt = (
            "Analyze these images of a SINGLE property to summarize its characteristics. "
            "1. Identify the AGGREGATED Architectural or Interior Style: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
            "2. 'room_color': Aggregate percentage (0-100) for Walls and Doors surfaces.\n"
            "3. 'element_color': Aggregate percentage (0-100) for Furniture surface area.\n"
            "4. Color order (14 colors): [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
            "5. Both color arrays must be exactly 14 integers summing to exactly 100.\n"
            "6. 'element_furniture': Array of exactly 14 STRINGS. Each string 'i' contains unique comma-separated furniture names in that color 'i'.\n"
            "7. STRICTLY EXCLUDE all electrical appliances (AC, washing machines, refrigerators, TVs, microwaves, etc.).\n"
            "8. COHERENCE RULE (CRITICAL): If 'element_furniture[i]' is NOT empty, 'element_color[i]' MUST be > 0. If 'element_color[i]' is 0, 'element_furniture[i]' MUST be \"\".\n"
            "9. NO REPETITION & LIMIT: List at most 10 unique items per color string. DO NOT repeat the same word (e.g., 'cabinet, cabinet' is FORBIDDEN). Use plural plural (e.g., 'chairs') instead of repeating."
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
                
                # บันทึกผลลัพธ์ที่ระดับ Property
                fs.db.collection("ARNON_properties").document(prop_id).update({
                    "architect_style": res.architect_style,
                    "room_color": res.room_color,
                    "element_color": res.element_color,
                    "element_furniture": res.element_furniture,
                    "analyzed": True,
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
