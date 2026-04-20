import os
import re
import time
import json
import logging
import requests
from io import BytesIO
from datetime import datetime, timedelta
from PIL import Image
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from typing import List
from dotenv import load_dotenv

from google import genai
from google.genai import types

from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

# Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

app = FastAPI(title="Property Color Analysis API", version="2.0")

# ==========================================================
# ⚙️ Config
# ==========================================================
FIRESTORE_COLLECTION = "Launch_Properties"

ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]

# ==========================================================
# Schema  (ตรงกับ arnon_step2_analyze_colors.py)
# ==========================================================
class AnalyzeRequest(BaseModel):
    property_id: int

class PropertyAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='ignore')
    architect_style: str = Field(description="Strictly ONE of: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.")
    poor_condition_image_indices: List[int] = Field(default_factory=list, description="Indices of images showing old/dirty condition.")
    raw_room_color: str = Field(description="Detailed raw colors. FORMAT exactly as: 'Walls: [color], Doors: [color], Floors: [color], Ceilings: [color]'")
    raw_furniture_color: str = Field(description="Detailed raw colors for various furniture elements (e.g. 'Sofa: Navy Blue, Bed: Oak Wood')")
    room_color: List[int] = Field(description="Aggregated 14-color percentage for structural elements (Walls, Doors, Floors, Ceilings) in order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    element_room: List[str] = Field(description="List of 14 strings. Each string 'i' contains comma-separated English names of structural elements (wall, door, floor, ceiling) in that color 'i'. If empty, use ''. Max 10 items per color.")
    element_color: List[int] = Field(description="Aggregated 14-color percentage for Furniture in the same order.")
    element_furniture: List[str] = Field(description="List of 14 strings. Each string 'i' contains unique comma-separated furniture names in that color 'i'. If empty, use ''. Max 10 items per color.")

# ==========================================================
# Helpers
# ==========================================================
def download_image_as_part(url: str, custom_headers: dict = None):
    """Download and compress image as Gemini Part (เนียนเป็น Browser เพื่อเลี่ยง 403)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-site",
    }
    if custom_headers:
        headers.update(custom_headers)
        
    try:
        # ลองดาวน์โหลดรูปภาพ
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.thumbnail((512, 512))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=80)
            return types.Part.from_bytes(data=buffer.getvalue(), mime_type='image/jpeg')
        else:
            logger.warning(f"[!] Download failed: Status {r.status_code} for URL (Referer: {headers.get('Referer')})")
    except Exception as e:
        logger.warning(f"[!] Download error: {e}")
    return None


def try_update_agent_api(property_id: int, payload: dict) -> str:
    """
    พยายามอัปเดต Agent API และคืนค่า 'primary', 'arnon' หรือ None ตามบัญชีที่สำเร็จ
    """
    # Primary account
    api_primary = APIService(
        email=os.getenv('AGENT_API_EMAIL'),
        password=os.getenv('AGENT_API_PASSWORD')
    )
    if api_primary.authenticate():
        if api_primary.update_property(str(property_id), payload):
            logger.info(f"✅ Agent API updated with primary account for {property_id}")
            return "primary"
        logger.warning(f"⚠️ Primary account failed to update {property_id}, trying Arnon account...")

    # Fallback to Arnon account
    arnon_email = os.getenv('AGENT_ARNON_EMAIL')
    arnon_password = os.getenv('AGENT_ARNON_PASSWORD')
    if arnon_email and arnon_password:
        api_arnon = APIService(email=arnon_email, password=arnon_password)
        if api_arnon.authenticate():
            if api_arnon.update_property(str(property_id), payload):
                logger.info(f"✅ Agent API updated with Arnon account for {property_id}")
                return "arnon"

    logger.error(f"❌ Agent API update failed for {property_id} (both accounts tried)")
    return None


def parse_specs_from_property(prop_data: dict) -> dict:
    """
    ดึง floors, bedrooms, bathrooms จาก property data ที่ได้จาก Agent API
    (เป็น dict ที่ได้จาก /api/agent/properties/{id})
    """
    specs = prop_data.get("specifications", {}) or {}
    return {
        "floors": str(specs.get("floors", "") or ""),
        "bedrooms": str(specs.get("bedrooms", "") or prop_data.get("bedrooms", "") or ""),
        "bathrooms": str(specs.get("bathrooms", "") or prop_data.get("bathrooms", "") or ""),
    }

# ==========================================================
# Background Worker
# ==========================================================
def process_property_analysis(property_id: int):
    logger.info(f"🚀 [Task Started] Processing Property ID: {property_id}")

    # 1. Initialize
    api_key = os.getenv('CLOUD_API_COLOR') or os.getenv('GEMINI_API_KEY_COLOR') or os.getenv('GEMINI_API_KEY')
    if not api_key:
        logger.error("❌ Gemini API Key not configured.")
        return

    client = genai.Client(api_key=api_key)
    api = APIService()
    api.authenticate()
    fs = FirestoreService()

    # 2. Fetch Property Detail from Agent API
    try:
        base = api.base_url.rstrip('/')
        url_prop = f"{base}/api/agent/properties/{property_id}/status"
        headers_prop = api._get_auth_headers()

        logger.info(f"   🌐 Fetching Detail: {url_prop}")
        r_prop = requests.get(url_prop, headers=headers_prop, timeout=15)
        res_json = r_prop.json()
        prop_data = res_json.get('data', res_json)

        # Check property type (condo vs house)
        prop_type_name = str(prop_data.get("property_type", {}).get("name", "")).strip()
        is_condo = "condo" in prop_type_name.lower() or "apartment" in prop_type_name.lower()

        # Get existing specs (floors, bedrooms, bathrooms)
        existing_specs = parse_specs_from_property(prop_data)

        images_info = prop_data.get('images', [])
        gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]

        if not gallery_images:
            logger.warning(f"⚠️ No gallery images for Property {property_id}.")
            return

        img_ids = [img.get("id") for img in gallery_images if img.get("id")]
        logger.info(f"📸 Found {len(img_ids)} gallery images")

    except Exception as e:
        logger.error(f"❌ Failed to fetch property data: {e}")
        return

    # 3. Refresh photo URLs
    try:
        url_map = {}
        refreshed = api.refresh_photo_urls(img_ids)
        if refreshed and isinstance(refreshed, dict):
            items = refreshed.get("refreshed_images") or refreshed.get("data", {}).get("refreshed_images", [])
            for item in items:
                url_map[str(item.get("id"))] = item.get("url")
    except Exception as e:
        logger.warning(f"⚠️ URL refresh failed: {e}")

    # 4. Download & compress images (ใช้ Signed URL ที่ได้จาก refreshing)
    image_parts = []
    original_image_ids = []
    
    # ดึงค่า Domain จาก API Base URL เพื่อทำ Referer ป้องกัน 403
    api_domain = api.base_url.split("//")[-1].split("/")[0]
    download_headers = {
        "Referer": f"https://{api_domain}/",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
    }

    for img_meta in gallery_images[:15]:
        img_id_str = str(img_meta.get("id"))
        # สำคัญ: ต้องใช้ Signed URL จาก map ที่เราเพิ่ง Refresh มา (ถ้ามี)
        img_url = url_map.get(img_id_str) or img_meta.get("url")
        
        part = download_image_as_part(img_url, custom_headers=download_headers)
        if part:
            image_parts.append(part)
            original_image_ids.append(img_id_str)

    if not image_parts:
        logger.error(f"❌ Could not download any images for Property {property_id}")
        return

    # 5. Build prompt (ตรงกับ arnon_step2)
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
        "6. 'element_room': Array of 14 strings. Each string 'i' contains ONLY elements from this strict list ['wall', 'door', 'floor', 'ceiling'] that appear in color index 'i'. DO NOT include any other words.\n"
        "7. 'element_color': Aggregate percentage (0-100) for Furniture.\n"
        "8. 'element_furniture': Array of 14 strings listing unique furniture items in each color index.\n"
        "9. Color order (14 colors): [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
        "10. Both color arrays must be exactly 14 integers summing to exactly 100.\n"
        "11. STRICTLY EXCLUDE all electrical appliances (AC, washing machines, refrigerators, TVs, microwaves, etc.).\n"
        "12. COHERENCE RULE (CRITICAL): If 'element_furniture[i]' is NOT empty, 'element_color[i]' MUST be > 0. If 'element_color[i]' is 0, 'element_furniture[i]' MUST be ''.\n"
        "13. NO REPETITION & LIMIT: List at most 10 unique items per color string.\n"
        "14. LIGHTING COMPENSATION (CRITICAL): Favor neutral colors like Gray (11), White (10), or Light Brown (9) for typical modern interiors unless a vibrant color is an explicit decorative choice."
    )

    contents = [prompt] + image_parts

    # 6. Gemini Analysis with retry
    logger.info(f"🎬 Analyzing {property_id} with {len(image_parts)} images...")
    res = None
    for attempt in range(3):
        try:
            time.sleep(3)
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
            break
        except Exception as e:
            err_msg = str(e)
            if ("503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg) and attempt < 2:
                wait = (attempt + 1) * 10
                logger.warning(f"⚠️ Gemini overloaded. Retry in {wait}s... (attempt {attempt+1}/3)")
                time.sleep(wait)
            else:
                logger.error(f"❌ Gemini Error for {property_id}: {e}")
                return

    if not res:
        logger.error(f"❌ No result from Gemini for {property_id}")
        return

    # 7. Post-process results
    now_iso = (datetime.utcnow() + timedelta(hours=7)).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    # คำนวณ house_color (อันดับ 1) และ house_color2 (อันดับ 2)
    # ให้น้ำหนักสีของห้อง (room) 70% และสีของเฟอร์นิเจอร์ (element) 30%
    # เพราะโครงสร้างห้อง (พื้น, ผนัง, เพดาน) มีพื้นที่นำสายตาและส่งผลต่อสีหลักมากกว่าเฟอร์นิเจอร์
    combined_colors = [
        ((res.room_color[i] if i < len(res.room_color) else 0) * 0.7)
        + ((res.element_color[i] if i < len(res.element_color) else 0) * 0.3)
        for i in range(14)
    ]
    sorted_idx = sorted(range(14), key=lambda k: combined_colors[k], reverse=True)
    house_color = ENGLISH_COLORS[sorted_idx[0]] if sum(combined_colors) > 0 else "Not Specified"
    house_color2 = ENGLISH_COLORS[sorted_idx[1]] if sum(combined_colors) > 0 and combined_colors[sorted_idx[1]] > 0 else ""

    # แมป poor condition image IDs
    poor_image_ids = [
        original_image_ids[idx]
        for idx in res.poor_condition_image_indices
        if 0 <= idx < len(original_image_ids)
    ]

    # 8. Update Agent API First: เพื่อดูว่าสำเร็จที่ Account ไหน จะได้เลือก Collection ใน Firestore ถูก
    specs_payload = {"style": res.architect_style}
    if existing_specs.get("floors"):
        specs_payload["floors"] = existing_specs["floors"]
    if existing_specs.get("bedrooms"):
        specs_payload["bedrooms"] = existing_specs["bedrooms"]
    if existing_specs.get("bathrooms"):
        specs_payload["bathrooms"] = existing_specs["bathrooms"]

    agent_update_payload = {
        "house_color": house_color,
        "specifications": specs_payload,
    }

    used_account = try_update_agent_api(property_id, agent_update_payload)
    
    if not used_account:
        logger.warning(f"⚠️ Skipping Firestore save for {property_id} because Agent API update failed for all accounts.")
    else:
        target_collection = "ARNON_properties" if used_account == "arnon" else "Leads"

        # 9. Save to Firestore (ใช้ Collection ตาม Account ที่อัปเดตสำเร็จ)
        raw_color_output = ", ".join([f"{ENGLISH_COLORS[i]}: {int(combined_colors[i])}" for i in range(14) if combined_colors[i] > 0])
        
        firestore_payload = {
            "raw_room_color": res.raw_room_color,
            "raw_furniture_color": res.raw_furniture_color,
            "raw_color": raw_color_output,
            "architect_style": res.architect_style,
            "room_color": res.room_color,
            "element_room": res.element_room,
            "element_color": res.element_color,
            "element_furniture": res.element_furniture,
            "house_color": house_color,
            "house_color2": house_color2,
            "analyzed": True,
            "analyzed_at": now_iso,
            "uploaded": True, # สำเร็จแน่นอนเพราะ used_account ไม่เป็น None
            "images_analyzed": len(image_parts),
        }
        if poor_image_ids:
            firestore_payload["poor_condition_image_ids"] = poor_image_ids

        try:
            doc_ref = fs.db.collection(target_collection).document(str(property_id))
            
            # ถ้าเป็น Leads ต้องค้นหาหาเอกสารที่มี api_property_id ตรงกันก่อน
            if target_collection == "Leads":
                query = fs.db.collection("Leads").where("api_property_id", "==", int(property_id)).limit(1).get()
                if query:
                    doc_ref = query[0].reference
                    logger.info(f"🔍 Found existing document in Leads for api_property_id {property_id}")
                else:
                    logger.warning(f"⚠️ Document with api_property_id {property_id} NOT found in Leads. Creating new with ID {property_id}.")

            doc_ref.set(firestore_payload, merge=True)
            logger.info(f"✅ Firestore updated in '{target_collection}' for {property_id}")
        except Exception as e:
            logger.error(f"❌ Firestore update failed for {property_id}: {e}")

    # 10. Upload to Staff API (color analysis payload - existing flow)
    try:
        api.authenticate_staff()
        formatted_furniture = []
        for s in res.element_furniture:
            if isinstance(s, str) and s.strip():
                formatted_furniture.append([item.strip() for item in s.split(",") if item.strip()])
            else:
                formatted_furniture.append([])

        staff_payload = {
            "property_id": int(property_id),
            "analyzed_at": now_iso,
            "average_color_hex": "#FFFFFF",
            "color": house_color,
            "room_color": res.room_color,
            "furniture_color": res.element_color,
            "furniture_elements": formatted_furniture,
            "interior_style": res.architect_style,
            "property_type": "condo" if is_condo else "house",
            "poor_condition_image_ids": poor_image_ids,
        }

        if api.submit_color_analysis(staff_payload):
            logger.info(f"✅ Staff API upload success for {property_id}")
        else:
            logger.error(f"❌ Staff API upload failed for {property_id}")
    except Exception as e:
        logger.error(f"❌ Staff API error for {property_id}: {e}")

    # 10. Update Agent API: house_color + specifications (with fallback to Arnon account)
    specs_payload = {"style": res.architect_style}
    if existing_specs.get("floors"):
        specs_payload["floors"] = existing_specs["floors"]
    if existing_specs.get("bedrooms"):
        specs_payload["bedrooms"] = existing_specs["bedrooms"]
    if existing_specs.get("bathrooms"):
        specs_payload["bathrooms"] = existing_specs["bathrooms"]

    agent_update_payload = {
        "house_color": house_color,
        "specifications": specs_payload,
    }

    try_update_agent_api(property_id, agent_update_payload)

    logger.info(f"🏁 [Task Completed] Property {property_id} fully processed.")


# ==========================================================
# Endpoint
# ==========================================================
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
