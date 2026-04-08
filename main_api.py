import os
import time
import json
import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from src.services.api_service import APIService

# Gemini Imports
from google import genai
from google.genai import types
from pydantic import Field, ConfigDict
from typing import List

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Environment Variabless
load_dotenv()

app = FastAPI(title="Property Color Analysis API", description="AI Image Analysis for Agent Uploads", version="1.0")

# ----------------- Schema -----------------
class AnalyzeRequest(BaseModel):
    property_id: int

class PropertyAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    architect_style: str = Field(description="Exterior/Interior architectural style: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other")
    poor_condition_image_indices: List[int] = Field(default_factory=list, description="List of integer indices (0-based) of images showing poor room condition.")
    raw_room_color: str = Field(description="The actual raw dominant color name of the room before mapping.")
    raw_furniture_color: str = Field(description="The actual raw dominant color name of the furniture before mapping.")
    room_color: List[int] = Field(description="Aggregated 14-color percentage for Walls and Doors in order.")
    element_color: List[int] = Field(description="Aggregated 14-color percentage for Furniture in the same 14-color order.")
    element_furniture: List[str] = Field(description="List of 14 strings containing comma-separated English names of furniture items in that color.")

THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู", 
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

# ----------------- Background Worker -----------------
def process_property_analysis(property_id: int):
    logger.info(f"🚀 [Task Started] Processing Property ID: {property_id}")
    
    # 1. Initialize Services
    api_key = os.getenv('CLOUD_API_COLOR') or os.getenv('GEMINI_API_KEY_COLOR') or os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("❌ Gemini API Key not configured.")
        return

    client = genai.Client(api_key=api_key)
    api = APIService() # 🚀 ปล่อยให้ APIService เลือก Email/Password จาก .env เองตามลำดับความสำคัญ
    api.authenticate()

    # 2. Get Property Status / Details
    status = api.get_property_status(property_id)
    logger.info(f"   Status for {property_id}: {status}")

    # 3. Retrieve and Refresh Photo URLs
    try:
        base = api.base_url.rstrip('/')
        if '/api' in base:
            url_prop = f"{base}/agent/properties/{property_id}/status"
        else:
            url_prop = f"{base}/api/agent/properties/{property_id}/status"
            
        headers_prop = api._get_auth_headers()
        import requests
        
        logger.info(f"   🌐 Fetching Detail from: {url_prop}")
        r_prop = requests.get(url_prop, headers=headers_prop, timeout=15)
        res_json = r_prop.json()
        
        prop_data = res_json.get('data', res_json) 
        images_info = prop_data.get('images', [])
        
        gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]
        
        if not gallery_images:
            logger.warning(f"⚠️ No 'gallery' images found for Property {property_id}.")
            return
            
        img_ids = [img.get("id") for img in gallery_images if img.get("id")]
        logger.info(f"📸 Found {len(img_ids)} gallery images to analyze.")
        
        logger.info(f"🔄 Refreshing Signed URLs for {len(img_ids)} images...")
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

        # โหลดภาพ
        pil_images = []
        original_image_ids = []
        from PIL import Image
        from io import BytesIO
        
        for img_meta in gallery_images[:15]:
            img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("url")
            try:
                r_img = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if r_img.status_code == 200:
                    img = Image.open(BytesIO(r_img.content))
                    img.thumbnail((640, 640))
                    pil_images.append(img)
                    original_image_ids.append(str(img_meta.get("id")))
            except Exception as e:
                pass
                
        if not pil_images:
             logger.error(f"❌ Could not download images for Property {property_id}")
             return

    except Exception as e:
        logger.error(f"❌ Failed to fetch property data for {property_id}: {e}")
        return

    # 4. Analyze with Gemini 
    logger.info(f"🎬 Analyzing Property {property_id} with {len(pil_images)} images via Gemini 3 Flash Preview...")
    prompt = (
        "Analyze these images of a SINGLE property to summarize its characteristics. The images are provided in a sequential list (Order: 0, 1, 2, ...).\n"
        "IMPORTANT: Images show the same rooms and furniture from DIFFERENT angles. DO NOT double-count items. \n"
        "1. Mental Mapping: Build a mental spatial map of the property. Identify unique furniture items (e.g., if you see the same blue bed in 3 photos, it counts as ONE blue bed).\n"
        "   - 'poor_condition_image_indices': Identify and list integer indices (0-based) of images showing an old, unrenovated, poorly maintained, cluttered, or dirty room condition. If none, return [].\n"
        "2. Identify the AGGREGATED Architectural or Interior Style: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
        "3. 'raw_room_color': Provide the true/raw dominant color name or hex of the room walls/floors before mapping.\n"
        "4. 'raw_furniture_color': Provide the true/raw dominant color name or hex of the furniture before mapping.\n"
        "5. 'room_color': Aggregate percentage (0-100) for ALL structural elements (Walls, Doors, Floors, Ceilings, and Roofs) based on the estimated total surface area.\n"
        "6. 'element_color': Aggregate percentage (0-100) for Furniture surface area. Deduplicate objects across images to prevent color inflation.\n"
        "7. Exact 14 Color order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black].\n"
        "8. Both color arrays must be exactly 14 integers summing to exactly 100.\n"
        "9. 'element_furniture': Array of exactly 14 STRINGS. comma-separated unique furniture names in that color.\n"
        "10. LIGHTING COMPENSATION (CRITICAL): Favor neutral colors like Gray (11), White (10), or Light Brown (9) unless a vibrant color like Pink (6) is an explicit decorative choice."
    )
    
    contents = [prompt] + pil_images
    
    try:
        # 🕒 Pacing
        time.sleep(2)
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PropertyAnalysisResponse,
                temperature=0.1
            )
        )
        res = response.parsed
        
        # 5. Format and Upload to Staff API
        logger.info(f"🎨 Uploading AI Result to Staff API for Property {property_id}...")
        
        api.authenticate_staff() # Login as Staff
        
        raw_furniture = res.element_furniture
        formatted_furniture = []
        for s in raw_furniture:
            if isinstance(s, str) and s.strip():
                items = [item.strip() for item in s.split(",") if item.strip()]
                formatted_furniture.append(items)
            else:
                formatted_furniture.append([])
                
        # แมป Index ภาพที่เก่า/สกปรก กลับไปเป็น Image ID
        poor_image_ids = []
        for idx in res.poor_condition_image_indices:
            if 0 <= idx < len(original_image_ids):
                poor_image_ids.append(original_image_ids[idx])

        # คำนวณสีรวม
        combined_colors = []
        for i in range(14):
            r_val = res.room_color[i] if i < len(res.room_color) else 0
            e_val = res.element_color[i] if i < len(res.element_color) else 0
            combined_colors.append(r_val + e_val)
            
        sorted_idx = sorted(range(len(combined_colors)), key=lambda k: combined_colors[k], reverse=True)
        dominant_color_thai = THAI_COLORS[sorted_idx[0]] if sum(combined_colors) > 0 else "ไม่ระบุ"
        
        from datetime import datetime, timedelta
        now_thailand = datetime.utcnow() + timedelta(hours=7)
        now_iso = now_thailand.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z' 

        struct_payload = {
            "property_id": int(property_id),
            "analyzed_at": now_iso,
            "average_color_hex": "#FFFFFF",
            "color": dominant_color_thai,
            "room_color": res.room_color,
            "furniture_color": res.element_color,
            "furniture_elements": formatted_furniture,
            "interior_style": res.architect_style,
            "property_type": "house",
            "poor_condition_image_ids": poor_image_ids # ⚠️ Staff API might need this field if supported
        }
        
        if api.submit_color_analysis(struct_payload):
             logger.info(f"✅ [Task Completed] Successfully analyzed Property {property_id}")
        else:
             logger.error(f"❌ [Task Completed with Error] Failed to upload for {property_id}")
             
    except Exception as e:
        logger.error(f"❌ [Task Failed] Gemini or API issue for {property_id}: {e}")

# ----------------- Endpoint -----------------
@app.post("/api/analyze-property")
async def trigger_property_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    if not req.property_id:
        raise HTTPException(status_code=400, detail="property_id is required")
        
    background_tasks.add_task(process_property_analysis, req.property_id)
    
    return {
        "success": True, 
        "message": f"Property ID {req.property_id} has been queued for AI Analysis.",
        "status": "processing_in_background"
    }
