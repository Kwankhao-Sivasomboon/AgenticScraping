import os
import requests
import json
import logging
from io import BytesIO
from PIL import Image
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv

from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

# Load environment
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main_api_true_color")

app = FastAPI(title="Property True Color Analysis API")

# Config
FIRESTORE_COLLECTION = "area_color"
ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู",
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

# 14 สีดิบ AI ตรงๆ (No Mapping)
THAI_COLORS_MAP = {
    "Green": "เขียว", "Brown": "น้ำตาล", "Red": "แดง", 
    "Dark Yellow": "เหลืองเข้ม", "Orange": "ส้ม", "Purple": "ม่วง", "Pink": "ชมพู",
    "Light Yellow": "เหลืองอ่อน", "Yellowish Brown": "น้ำตาลอมเหลือง", "Light Brown": "น้ำตาลอ่อน",
    "White": "ขาว", "Gray": "เทา", "Blue": "น้ำเงิน", "Black": "ดำ"
}

# --- Schema ---
class FurnitureItem(BaseModel):
    name: str = Field(description="Name of the furniture item (English)")
    area_percentage: float = Field(description="Percentage of the TOTAL property surface area this item occupies.")

class FurnitureElements(BaseModel):
    Green: List[str] = Field(default_factory=list)
    Brown: List[str] = Field(default_factory=list)
    Red: List[str] = Field(default_factory=list)
    Dark_Yellow: List[str] = Field(default_factory=list, alias="Dark Yellow")
    Orange: List[str] = Field(default_factory=list)
    Purple: List[str] = Field(default_factory=list)
    Pink: List[str] = Field(default_factory=list)
    Light_Yellow: List[str] = Field(default_factory=list, alias="Light Yellow")
    Yellowish_Brown: List[str] = Field(default_factory=list, alias="Yellowish Brown")
    Light_Brown: List[str] = Field(default_factory=list, alias="Light Brown")
    White: List[str] = Field(default_factory=list)
    Gray: List[str] = Field(default_factory=list)
    Blue: List[str] = Field(default_factory=list)
    Black: List[str] = Field(default_factory=list)

class RoomElementBreakdown(BaseModel):
    wall: float = Field(description="Percentage for wall")
    floor: float = Field(description="Percentage for floor")
    ceiling: float = Field(description="Percentage for ceiling")
    door: float = Field(description="Percentage for door")

class StructuralColors(BaseModel):
    wall: List[int] = Field(description="14-integer array (sum=100) for WALL colors.")
    floor: List[int] = Field(description="14-integer array (sum=100) for FLOOR colors.")
    ceiling: List[int] = Field(description="14-integer array (sum=100) for CEILING colors.")
    door: List[int] = Field(description="14-integer array (sum=100) for DOOR colors.")

class PropertyAnalysisTrueColor(BaseModel):
    # 🏠 Room Structure Colors Details
    structural_colors: StructuralColors
    
    # 🧩 Room Element Percentage Breakdown (Sum 100)
    room_element_breakdown: RoomElementBreakdown
    
    # 🛋️ Furniture Colors (Sum 100)
    furniture_color_composition: List[int] = Field(description="Percentages for [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    
    # 🎨 Furniture Elements Mapping
    furniture_elements: FurnitureElements
    
    # 📏 Physical Area Weight (Room vs Furniture)
    # Total physical area = Room Area + Furniture Area = 100%
    room_weight: float = Field(description="Estimated physical surface area weight of the room structures (0.0 - 1.0)")
    furniture_weight: float = Field(description="Estimated physical surface area weight of the furniture (0.0 - 1.0)")
    
    # 🏛️ Style
    architect_style: str = Field(description="Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, or Other")
    
    # Detailed Furniture Breakdown
    furniture_details: List[FurnitureItem] = Field(description="List of every unique furniture item found and its area percentage relative to the TOTAL physical surface area.")
    
    raw_room_color: str = Field(description="Raw description of colors for Walls, Doors, Floors, Ceilings.")
    raw_furniture_color: str = Field(description="Raw description of colors for furniture items.")
    poor_condition_image_indices: List[int] = Field(description="Indices of images showing severe damage.")

# --- Helpers ---
def download_image_as_part(url: str, agent_token: str = None, base_url: str = None):
    if not url: return None, None
    original_url = url
    if not url.startswith(('http://', 'https://')):
        if base_url:
            clean_base = base_url.rstrip('/')
            if clean_base.endswith('/api'): clean_base = clean_base[:-4]
            url = f"{clean_base}/{url.lstrip('/')}"
        else: return None, None
    headers = {"User-Agent": "Mozilla/5.0"}
    if agent_token: headers["Authorization"] = f"Bearer {agent_token}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            if img.mode != 'RGB': img = img.convert('RGB')
            img.thumbnail((512, 512))
            buffer = BytesIO()
            img.save(buffer, format="WEBP", quality=80)
            return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/webp"), 200
        elif r.status_code == 404 and "/storage/" not in url and base_url:
            clean_base = base_url.rstrip('/')
            if clean_base.endswith('/api'): clean_base = clean_base[:-4]
            fallback_img_url = f"{clean_base}/storage/{original_url.lstrip('/')}"
            r2 = requests.get(fallback_img_url, headers=headers, timeout=15)
            if r2.status_code == 200:
                img = Image.open(BytesIO(r2.content))
                if img.mode != 'RGB': img = img.convert('RGB')
                img.thumbnail((512, 512))
                buffer = BytesIO()
                img.save(buffer, format="WEBP", quality=80)
                return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/webp"), 200
            return None, r2.status_code
        return None, r.status_code
    except: return None, 500

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

# --- Main Logic ---
async def process_true_color_analysis(property_id: int):
    api = APIService()
    api.authenticate()
    fs = FirestoreService()
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_COLOR"))
    
    # 1. Fetch Property Detail & Check Owner
    base_url = api.base_url.rstrip('/')
    is_arnon_owner = False
    prop_type_name = "Unknown"
    is_condo = False
    existing_specs = {}

    # 0. Initialize & Authenticate
    api = APIService()
    if not api.authenticate():
        logger.error("❌ Initial Agent API authentication failed on both Primary and Fallback URLs.")
        return
    
    # 1. Fetch Property Data with Fallback support
    try:
        current_api = api
        prop_data = current_api.get_property_detail(property_id)
        
        if not prop_data or prop_data == "forbidden":
            logger.error(f"❌ Cannot fetch property {property_id} (Forbidden or Not Found)")
            return

        # Check Owner Email for switching to Arnon if needed
        owner_email = prop_data.get("owner", {}).get("email", "").lower()
        arnon_email = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
        is_arnon_owner = (owner_email == arnon_email)

        if is_arnon_owner and current_api.email != arnon_email:
            logger.info(f"🎯 Property owner is Arnon. Switching to Arnon account...")
            api_arnon = APIService()
            if api_arnon.authenticate(use_arnon=True):
                current_api = api_arnon
                prop_data = current_api.get_property_detail(property_id)
        
        prop_type_name = prop_data.get("property_type", {}).get("name", "")
        is_condo = "condo" in prop_type_name.lower() or "apartment" in prop_type_name.lower()
        
        # Extract existing specs
        raw_specs = prop_data.get("specifications", {}) or prop_data.get("specs", {})
        if isinstance(raw_specs, dict): existing_specs = raw_specs
        
        images_info = prop_data.get("images_info", [])
    except Exception as e:
        logger.error(f"❌ Failed to fetch property {property_id}: {e}")
        return

    # 2. Refresh & Download Images
    gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]
    img_ids = [img.get("id") for img in gallery_images if img.get("id")]
    refreshed = current_api.refresh_photo_urls(img_ids)
    url_map = {str(item.get("id")): item.get("url") for item in (refreshed if refreshed else [])}
    
    image_parts, original_image_ids = [], []
    for img_meta in gallery_images[:15]:
        img_id_str = str(img_meta.get("id"))
        img_url = url_map.get(img_id_str) or img_meta.get("url")
        part, _ = download_image_as_part(img_url, agent_token=current_api.token, base_url=current_api.base_url)
        if part:
            image_parts.append(part)
            original_image_ids.append(img_id_str)
    
    if not image_parts: 
        logger.warning(f"⚠️ No images to analyze for {property_id}")
        return

    # 3. Gemini Analysis (True Color Logic - 100/100 Spatial Map)
    prompt = (
        "Build a 3D mental spatial map of this property based on all provided images. "
        "Compensate for camera perspective distortion to estimate TRUE physical surface areas.\n"
        "1. 'room_element_breakdown': Estimate physical area % of the structural parts (must sum to exactly 100): 'wall', 'floor', 'ceiling', 'door'.\n"
        "2. 'structural_colors': For EACH structural part (wall, floor, ceiling, door), provide a 14-integer array (sum=100) representing the color composition of THAT part only.\n"
        "3. 'furniture_color_composition': 14-integer array (sum=100) for physical area % of Furniture ONLY.\n"
        "4. 'furniture_elements': For each of the 14 color fields (Green, Brown, Red, Dark_Yellow, Orange, Purple, Pink, Light_Yellow, Yellowish_Brown, Light_Brown, White, Gray, Blue, Black), "
        "provide a list of unique furniture item names found in that color. Use [] for colors with no furniture.\n"
        "5. 'room_weight': Float 0.0-1.0 representing the fraction of TOTAL visible physical area occupied by room structures (walls+floors+doors+ceilings).\n"
        "   'furniture_weight': Float 0.0-1.0 representing the fraction occupied by furniture. room_weight + furniture_weight = 1.0.\n"
        "6. 'furniture_details': List every unique furniture item with its 'name' and 'area_percentage' relative to TOTAL physical surface area.\n"
        "7. Color order for all arrays: [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
        "8. 'architect_style': Choose ONE from: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
        "9. NO lighting/reflection artifacts. Identify TRUE material colors as seen in neutral daylight.\n"
        "10. STRICTLY EXCLUDE electrical appliances (AC, TV, refrigerator, washing machine, etc.).\n"
        "11. STRICTLY EXCLUDE nature, trees, plants, grass, and garden elements. Focus ONLY on the Building Facade and Man-made materials.\n"
        "12. TONE PRIORITY: If a material color is ambiguous between a warm tone (Cream, Beige, Light Brown) and a cool tone (Gray, White), PRIORITIZE the warm tone."
    )

    try:
        res = None
        for attempt in range(3):
            # ใช้ gemini-3.1-flash-lite-preview เป็นตัวหลัก ห้ามแก้!!!
            current_model = "gemini-2.5-flash" if attempt < 2 else "gemini-3.1-flash-lite-preview"
            try:
                response = client.models.generate_content(
                    model=current_model,
                    contents=[prompt] + image_parts,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=PropertyAnalysisTrueColor,
                        temperature=0.1
                    )
                )
                res = response.parsed
                break
            except Exception as e:
                err_msg = str(e)
                if ("503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg) and attempt < 2:
                    wait = (attempt + 1) * 5
                    logger.warning(f"⚠️ Gemini overloaded ({current_model}). Retry in {wait}s...")
                    time.sleep(wait)
                else:
                    raise e
        
        if not res:
            logger.error(f"❌ No result from Gemini for {property_id}")
            return
        
        # Calculate overall dominant color based on Spatial Weights
        room_weight = res.room_weight
        furn_weight = res.furniture_weight

        # 1. คำนวณ Room Score แบบปกติ (1:1:1:1 ตาม Breakdown) - ลอจิกเดียวกับ Report
        room_comp_floats = []
        for i in range(14):
            val = (
                (res.structural_colors.wall[i] * res.room_element_breakdown.wall / 100) + 
                (res.structural_colors.floor[i] * res.room_element_breakdown.floor / 100) +
                (res.structural_colors.ceiling[i] * res.room_element_breakdown.ceiling / 100) + 
                (res.structural_colors.door[i] * res.room_element_breakdown.door / 100)
            )
            room_comp_floats.append(round(val))
            
        # Normalize to strictly sum to 100
        diff = 100 - sum(room_comp_floats)
        if diff != 0:
            max_idx_room = room_comp_floats.index(max(room_comp_floats))
            room_comp_floats[max_idx_room] += diff

        combined_colors = [
            ((room_comp_floats[i] if i < len(room_comp_floats) else 0) * room_weight)
            + ((res.furniture_color_composition[i] if i < len(res.furniture_color_composition) else 0) * furn_weight)
            for i in range(14)
        ]
        
        # หาผู้ชนะจาก 14 สีตรงๆ (No Mapping)
        max_score = -1
        winner_idx = 10 # Default White
        for i, score in enumerate(combined_colors):
            if score > max_score:
                max_score = score
                winner_idx = i
                
        house_color = ENGLISH_COLORS[winner_idx]
        house_color_thai = THAI_COLORS_MAP.get(house_color, "ขาว")
        
        # หา Runner up (House Color 2)
        sorted_scores = sorted(enumerate(combined_colors), key=lambda x: x[1], reverse=True)
        house_color2 = ENGLISH_COLORS[sorted_scores[1][0]] if len(sorted_scores) > 1 and sorted_scores[1][1] > 0 else None
        house_color2_thai = THAI_COLORS_MAP.get(house_color2) if house_color2 else None

        specs_payload = {
            "style": res.architect_style,
            "house_color": house_color,
            "color": house_color_thai,
            "house_color2": house_color2,
            "color2": house_color2_thai,
            "area_breakdown": {"room": room_weight * 100, "furniture": furn_weight * 100},
            "area_weight": {"room": room_weight * 100, "furniture": furn_weight * 100}
        }
        for k in ["floors", "bedrooms", "bathrooms"]:
            if existing_specs.get(k): specs_payload[k] = existing_specs[k]

        agent_update_payload = {
            "specifications": specs_payload, 
            "specs": specs_payload, 
            "house_color": house_color,
            "house_color2": house_color2
        }
        logger.info(f"📤 Updating Agent API for {property_id} with: {house_color}")
        used_account = try_update_agent_api(current_api, property_id, agent_update_payload, force_arnon=is_arnon_owner)
    
        # 6. Upload Color Breakdown to STAFF API
        if res.structural_colors or res.furniture_elements:
            logger.info(f"📤 Uploading detailed colors to Staff API...")
            
            formatted_struct = {}
            for part in ["wall", "floor", "ceiling", "door"]:
                formatted_struct[part] = {ENGLISH_COLORS[i]: res.structural_colors.model_dump()[part][i] for i in range(14)}

            furn_elements_dict = res.furniture_elements.model_dump(by_alias=True)
            formatted_furn_elements = [furn_elements_dict.get(color, [])[:5] for color in ENGLISH_COLORS]

            staff_payload = {
                "property_id": int(property_id),
                "analyzed_at": (datetime.utcnow() + timedelta(hours=7)).isoformat() + "Z",
                "color": house_color_thai,
                "room_color": {ENGLISH_COLORS[i]: room_comp_floats[i] for i in range(14)},
                "furniture_color": {ENGLISH_COLORS[i]: res.furniture_color_composition[i] for i in range(14)},
                "furniture_elements": formatted_furn_elements,
                "structural_colors": formatted_struct,
                "room_element_breakdown": res.room_element_breakdown.model_dump(),
                "house_color": house_color,
                "interior_style": res.architect_style,
                "property_type": prop_type_name
            }
            current_api.submit_color_analysis(staff_payload)

        # 5. Save to Firestore
        fs_payload = {
            "raw_room_color": res.raw_room_color,
            "raw_furniture_color": res.raw_furniture_color,
            "architect_style": res.architect_style,
            "room_color_composition": room_comp_floats,
            "structural_colors": res.structural_colors.model_dump(),
            "room_element_breakdown": res.room_element_breakdown.model_dump(),
            "furniture_color_composition": res.furniture_color_composition,
            "furniture_elements": res.furniture_elements.model_dump(by_alias=True),
            "house_color": house_color,
            "house_color_thai": house_color_thai,
            "true_color_analyzed": True,
            "analyzed_at": now_iso,
            "uploaded": True,
            "images_analyzed": len(image_parts),
            "property_id": int(property_id),
            "area_weight": {
                "room": room_weight * 100,
                "furniture": furn_weight * 100
            }
        }
        target_coll = "ARNON_properties_true_color" if used_account == "arnon" else FIRESTORE_COLLECTION
        fs.db.collection(target_coll).document(str(property_id)).set(fs_payload, merge=True)
        
        # 6. Upload to Staff API
        try:
            current_api.authenticate_staff()
            
            # แปลง structural_colors เป็น Dict of Dicts สำหรับ API
            formatted_struct = {}
            for part in ["wall", "floor", "ceiling", "door"]:
                formatted_struct[part] = {ENGLISH_COLORS[i]: res.structural_colors.model_dump()[part][i] for i in range(14)}

            # แปลง furniture_elements เป็น List of 14 Lists
            furn_elements_dict = res.furniture_elements.model_dump(by_alias=True)
            formatted_furn_elements = []
            for color in ENGLISH_COLORS:
                formatted_furn_elements.append(furn_elements_dict.get(color, [])[:5])

            staff_payload = {
                "property_id": int(property_id),
                "analyzed_at": now_iso,
                "color": house_color_thai,
                "room_color": {ENGLISH_COLORS[i]: room_comp_floats[i] for i in range(14)},
                "furniture_color": {ENGLISH_COLORS[i]: res.furniture_color_composition[i] for i in range(14)},
                "furniture_elements": formatted_furn_elements, # เปลี่ยนเป็น List of Lists
                "structural_colors": formatted_struct,
                "room_element_breakdown": res.room_element_breakdown.model_dump(),
                "house_color": house_color,
                "interior_style": res.architect_style,
                "property_type": prop_type_name
            }
            if current_api.submit_color_analysis(staff_payload):
                logger.info(f"✅ Staff API upload success for {property_id}")
            else:
                logger.error(f"❌ Staff API upload failed for {property_id}")
        except Exception as e:
            logger.error(f"❌ Staff API error: {e}")

        logger.info(f"✅ True Color Analysis Success for {property_id}")
        
    except Exception as e:
        logger.error(f"❌ Analysis error for {property_id}: {e}")

@app.post("/api/analyze-true-color/{property_id}")
async def analyze_true_color(property_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(process_true_color_analysis, property_id)
    return {"status": "processing", "property_id": property_id, "mode": "true_color"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
