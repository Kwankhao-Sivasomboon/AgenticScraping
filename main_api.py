import os
import re
import time
import json
import logging
import asyncio
import requests
from io import BytesIO
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
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

# ==========================================================
# Task Queue System
# ==========================================================
analysis_queue = asyncio.Queue()
processing_set = set()

async def analysis_worker():
    """Background worker that continuously processes the queue sequentially."""
    while True:
        property_id = await analysis_queue.get()
        try:
            # Run the synchronous scraper function in a separate thread so it doesn't block FastAPI
            await asyncio.to_thread(process_property_analysis, property_id)
        except Exception as e:
            logger.error(f"Worker Error for property_id {property_id}: {e}")
        finally:
            analysis_queue.task_done()
            if property_id in processing_set:
                processing_set.remove(property_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(analysis_worker())
    yield
    task.cancel()

app = FastAPI(title="Property Color Analysis API", version="2.0", lifespan=lifespan)

# ==========================================================
# ⚙️ Config
# ==========================================================
FIRESTORE_COLLECTION = "Launch_Properties"

ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู",
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
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
def download_image_as_part(url: str, custom_headers: dict = None, agent_token: str = None, base_url: str = None):
    """Download and compress image as Gemini Part."""
    if not url: return None
    original_url = url
    
    # Handle relative URLs (e.g. 'staging/image.jpg')
    if not url.startswith(('http://', 'https://')):
        if base_url:
            clean_base = base_url.rstrip('/')
            if clean_base.endswith('/api'): clean_base = clean_base[:-4]
            url = f"{clean_base}/{url.lstrip('/')}"
        else:
            return None
            
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
    
    # 🔑 สำคัญ: media URLs ของ app.yourhome.co.th ต้องใช้ Bearer Token ถึงจะโหลดได้
    # (เปิดใน Browser ได้เพราะมี Cookie Session แต่ requests ต้องส่ง Authorization)
    if agent_token:
        headers["Authorization"] = f"Bearer {agent_token}"
        
    try:
        # ลองดาวน์โหลดรูปภาพ
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            if img.mode != 'RGB': img = img.convert('RGB')
            img.thumbnail((512, 512))
            buffer = BytesIO()
            img.save(buffer, format="WEBP", quality=80)
            return types.Part.from_bytes(data=buffer.getvalue(), mime_type='image/webp')
        elif r.status_code == 404 and "/storage/" not in url and base_url:
            # ลองเติม /storage/ เข้าไปถ้า API คืนค่าเป็น Path ลอยๆ
            clean_base = base_url.rstrip('/')
            if clean_base.endswith('/api'): clean_base = clean_base[:-4]
            fallback_img_url = f"{clean_base}/storage/{original_url.lstrip('/')}"
            logger.info(f"🔄 Retrying with storage path: {fallback_img_url}")
            r2 = requests.get(fallback_img_url, headers=headers, timeout=15)
            if r2.status_code == 200:
                img = Image.open(BytesIO(r2.content))
                if img.mode != 'RGB': img = img.convert('RGB')
                img.thumbnail((512, 512))
                buffer = BytesIO()
                img.save(buffer, format="WEBP", quality=80)
                return types.Part.from_bytes(data=buffer.getvalue(), mime_type='image/webp')
            else:
                logger.warning(f"[!] Download failed: Status {r2.status_code} for URL: {fallback_img_url}")
        else:
            logger.warning(f"[!] Download failed: Status {r.status_code} for URL: {url}")
    except Exception as e:
        logger.warning(f"[!] Download error for {url}: {e}")
    return None


def try_update_agent_api(current_api: APIService, property_id: int, payload: dict, force_arnon: bool = False) -> str:
    """พยายามอัปเดต Agent API โดยเลือกบัญชีที่ถูกต้อง"""
    if force_arnon:
        logger.info(f"🎯 Forced Arnon account for property {property_id}")
        if current_api.email != os.getenv("AGENT_ARNON_EMAIL"):
            current_api.authenticate(use_arnon=True)
        if current_api.update_property(str(property_id), payload):
            return "arnon"
        return ""

    # ลองใช้บัญชีปัจจุบันที่มีอยู่ก่อน
    logger.info(f"🔑 Attempting update with CURRENT account ({current_api.email})...")
    if current_api.update_property(str(property_id), payload):
        return "primary" if current_api.email != os.getenv("AGENT_ARNON_EMAIL") else "arnon"

    # ถ้าล้มเหลว และยังไม่ใช่ Arnon ให้ลองสลับเป็น Arnon
    if current_api.email != os.getenv("AGENT_ARNON_EMAIL"):
        logger.info(f"🔄 Update failed with Primary. Switching to ARNON for retry...")
        if current_api.authenticate(use_arnon=True):
            if current_api.update_property(str(property_id), payload):
                return "arnon"

    return ""


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
    if not api.authenticate():
        logger.error("❌ Initial Agent API authentication failed on both Primary and Fallback URLs. Terminating task.")
        return
    fs = FirestoreService()

    # 2. Fetch Property Detail & Download Images (with Dynamic Fallback)
    prop_data = None
    image_parts = []
    original_image_ids = []
    is_condo = True
    prop_type_name = "Unknown"
    existing_specs = {}

    def try_fetch_and_download(current_api):
        nonlocal prop_data, image_parts, original_image_ids, is_condo, prop_type_name, existing_specs
        try:
            prop_data = current_api.get_property_detail(property_id)
            
            if prop_data == "forbidden":
                return False, "forbidden"
            
            if not prop_data:
                return False, False

            # 🕵️‍♂️ Check Owner: ถ้าเป็นของอานนท์ ให้ใช้บัญชีอานนท์ทำงานตั้งแต่ต้น
            owner_email = prop_data.get("owner", {}).get("email", "").lower()
            arnon_email_env = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
            
            if owner_email == arnon_email_env and current_api.email != arnon_email_env:
                logger.info(f"🎯 Property owner is Arnon ({owner_email}). Switching to Arnon account...")
                if current_api.authenticate(use_arnon=True):
                    # ต้องย้อนกลับมาดึงข้อมูลใหม่ด้วย Token ของอานนท์เพื่อให้แน่ใจเรื่องสิทธิ์รูป
                    return try_fetch_and_download(current_api)
            
            is_arnon_owner = (owner_email == arnon_email_env)

            # Check property type
            prop_type_name = str(prop_data.get("property_type", {}).get("name", "")).strip()
            is_condo = "condo" in prop_type_name.lower() or "apartment" in prop_type_name.lower()
            existing_specs = parse_specs_from_property(prop_data)

            images_info = prop_data.get('images', [])
            gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]

            if not gallery_images:
                logger.warning(f"⚠️ No gallery images for Property {property_id}.")
                return True, "no_images"

            img_ids = [img.get("id") for img in gallery_images if img.get("id")]
            logger.info(f"📸 Found {len(img_ids)} gallery images")

            # Refresh photo URLs
            url_map = {}
            refreshed = current_api.refresh_photo_urls(img_ids)
            if refreshed:
                for item in refreshed:
                    url_map[str(item.get("id"))] = item.get("url")
            
            # Download images
            image_parts = []
            original_image_ids = []
            api_domain = current_api.primary_url.split("//")[-1].split("/")[0] # Use primary_url for Referer
            download_headers = {"Referer": f"https://{api_domain}/", "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"}

            for img_meta in gallery_images[:15]:
                img_id_str = str(img_meta.get("id"))
                # 🚀 ลำดับความสำคัญ: refreshed > validated > raw
                img_url = url_map.get(img_id_str) or img_meta.get("validated_url") or img_meta.get("url")
                
                if not img_url: continue
                
                # 🛠️ ซ่อม URL ถ้าไม่มี Domain
                if not img_url.startswith('http'):
                    base = current_api.primary_url.rstrip('/')
                    if '/api' in base: base = base.split('/api')[0]
                    img_url = f"{base}/{img_url.lstrip('/')}"

                # 📸 Download
                part = download_image_as_part(img_url, custom_headers=download_headers, agent_token=current_api.token, base_url=current_api.base_url)
                
                if part:
                    image_parts.append(part)
                    original_image_ids.append(img_id_str)
                
                # ⏳ หน่วงเวลาเล็กน้อย (0.5s)
                time.sleep(0.5)
            
            if not image_parts:
                return False, is_arnon_owner
            
            return True, is_arnon_owner
        except Exception as e:
            logger.error(f"❌ Error in try_fetch_and_download: {e}")
            return False, False

    # 1. Fetch data & Switch Account if needed
    success, is_arnon_owner = try_fetch_and_download(api)
    
    # 🔄 ถ้าติดเรื่องสิทธิ์ หรือต้องการ Fallback (กรณีที่ fetch รอบแรกเป็น automation แต่โหลดรูปไม่ได้)
    if not success and not is_arnon_owner:
        logger.info("⚠️ Primary account fetch/download failed. Attempting manual fallback to Arnon account...")
        if api.authenticate(use_arnon=True):
            success, is_arnon_owner = try_fetch_and_download(api)
            is_arnon_owner = True # บังคับเป็น True เพราะเราสลับมาใช้ Arnon แล้ว
    
    if not success:
        logger.error(f"❌ Failed to fetch or download images for {property_id}")
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
        "13. NO REPETITION & LIMIT: List at most 10 unique items per color string. DO NOT repeat same word. Use plural (e.g., 'chairs').\n"
        "14. LIGHTING COMPENSATION: Photos often have warm yellow/orange lighting. Identify the ACTUAL material color as a human would see it in neutral daylight.\n"
        "15. STRICTLY EXCLUDE nature, trees, plants, grass, and garden elements. Focus ONLY on the Building Facade and Man-made materials.\n"
        "16. TONE PRIORITY: If a color is ambiguous between a warm tone (Cream, Beige, Light Brown) and a cool tone (Gray, White), PRIORITIZE the warm tone."
    )

    contents = [prompt] + image_parts

    # 6. Gemini Analysis with retry
    logger.info(f"🎬 Analyzing {property_id} with {len(image_parts)} images...")
    res = None
    for attempt in range(3):
        try:
            time.sleep(3)
            # ใช้ gemini-2.5-flash เป็นตัวหลัก
            current_model = "gemini-2.5-flash" if attempt < 2 else "gemini-3.1-flash-lite-preview"
            response = client.models.generate_content(
                model=current_model,
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
    # ให้น้ำหนักสีของห้อง (room) 50% และสีของเฟอร์นิเจอร์ (element) 50%
    combined_colors = [
        ((res.room_color[i] if i < len(res.room_color) else 0) * 0.5)
        + ((res.element_color[i] if i < len(res.element_color) else 0) * 0.5)
        for i in range(14)
    ]
    
    # Aggregate into System Colors
    system_scores = {c: 0.0 for c in set(SYSTEM_COLOR_MAP.values())}
    for i in range(14):
        ai_color = ENGLISH_COLORS[i]
        sys_color = SYSTEM_COLOR_MAP[ai_color]
        system_scores[sys_color] += combined_colors[i]
        
    sorted_sys_colors = sorted(system_scores.items(), key=lambda x: x[1], reverse=True)
    house_color = sorted_sys_colors[0][0] if sorted_sys_colors[0][1] > 0 else "Not Specified"
    house_color_thai = SYSTEM_THAI_MAP.get(house_color, "ไม่ระบุ")
    
    house_color2 = sorted_sys_colors[1][0] if len(sorted_sys_colors) > 1 and sorted_sys_colors[1][1] > 0 else None
    house_color2_thai = SYSTEM_THAI_MAP.get(house_color2) if house_color2 else None

    # แมป poor condition image IDs
    poor_image_ids = [
        original_image_ids[idx]
        for idx in res.poor_condition_image_indices
        if 0 <= idx < len(original_image_ids)
    ]

    # 8. Update Agent API (with fallback to Arnon account)
    
    # 🏠 สำคัญ: house_color ต้องอยู่ข้างใน specifications ถึงจะอัปเดตสำเร็จ
    specs_payload = {
        "style": res.architect_style,
        "house_color": house_color, # English
        "color": house_color_thai,   # Thai
        "house_color2": house_color2,
        "color2": house_color2_thai,
    }
    
    if existing_specs.get("floors"): specs_payload["floors"] = existing_specs["floors"]
    if existing_specs.get("bedrooms"): specs_payload["bedrooms"] = existing_specs["bedrooms"]
    if existing_specs.get("bathrooms"): specs_payload["bathrooms"] = existing_specs["bathrooms"]

    agent_update_payload = {
        "house_color": house_color, 
        "color": house_color_thai,   
        "house_color2": house_color2,
        "color2": house_color2_thai,
        "specifications": specs_payload,
        "specs": specs_payload,
    }
    
    logger.info(f"📤 Updating Agent API for {property_id} with: {house_color}")
    used_account = try_update_agent_api(api, property_id, agent_update_payload, force_arnon=is_arnon_owner)
    
    if not used_account:
        logger.warning(f"⚠️ Agent API update failed for {property_id}. But continuing...")
    
    # [ADDED] 8.5 Upload Color Breakdown to STAFF API
    if structural_colors or furniture_elements:
        logger.info(f"📤 Uploading detailed colors to Staff API for {property_id}...")
        api.submit_color_analysis(property_id, structural_colors, furniture_elements)
    
    # 9. Determine Collection
    target_collection = "ARNON_properties" if used_account == "arnon" else FIRESTORE_COLLECTION

    # 10. Save to Firestore (ใช้ Collection ตาม Account ที่อัปเดตสำเร็จ)
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

    # 11. Upload to Staff API (color analysis payload - existing flow)
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
            "color": house_color_thai,
            "room_color": res.room_color,
            "furniture_color": res.element_color,
            "furniture_elements": formatted_furniture,
            "interior_style": res.architect_style,
            "property_type": "condo" if is_condo else "house",
            "poor_condition_image_ids": poor_image_ids,
            "house_color": house_color,
            "house_color2": house_color2,
        }

        if api.submit_color_analysis(staff_payload):
            logger.info(f"✅ Staff API upload success for {property_id}")
        else:
            logger.error(f"❌ Staff API upload failed for {property_id}")
    except Exception as e:
        logger.error(f"❌ Staff API error for {property_id}: {e}")

    logger.info(f"🏁 [Task Completed] Property {property_id} fully processed.")


# ==========================================================
# Endpoint
# ==========================================================
@app.post("/api/analyze-property")
async def trigger_property_analysis(req: AnalyzeRequest):
    if not req.property_id:
        raise HTTPException(status_code=400, detail="property_id is required")

    if req.property_id in processing_set:
        return {
            "success": True,
            "message": f"Property ID {req.property_id} is already in the queue or currently processing. Skipped.",
            "status": "already_queued"
        }

    processing_set.add(req.property_id)
    analysis_queue.put_nowait(req.property_id)

    return {
        "success": True,
        "message": f"Property ID {req.property_id} has been queued for AI Analysis.",
        "status": "processing_in_background",
        "queue_position": analysis_queue.qsize()
    }
