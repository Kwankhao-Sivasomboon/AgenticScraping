import os
import requests
import json
import logging
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
FIRESTORE_COLLECTION = "arnon_properties_true_color"
ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู",
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

# --- Schema ---
class FurnitureItem(BaseModel):
    name: str = Field(description="Name of the furniture item (English)")
    area_percentage: float = Field(description="Percentage of the TOTAL image area this item occupies.")

class PropertyAnalysisTrueColor(BaseModel):
    architect_style: str = Field(description="Architectural or Interior style (Modern, Nordic, etc.)")
    raw_room_color: str = Field(description="Raw description of colors for Walls, Doors, Floors, Ceilings.")
    raw_furniture_color: str = Field(description="Raw description of colors for each unique furniture item.")
    total_color_composition: List[int] = Field(description="Aggregated 14-color percentage (sum 100) including EVERYTHING.")
    area_breakdown: Dict[str, float] = Field(description="Percentage of area occupied by: walls, floors, doors, ceilings, furniture.")
    furniture_details: List[FurnitureItem] = Field(description="List of each unique furniture item and its area percentage.")
    poor_condition_image_indices: List[int] = Field(description="Indices of images showing severe damage.")

# --- Helpers ---
def download_image_as_part(url: str, agent_token: str = None):
    headers = {"User-Agent": "Mozilla/5.0"}
    if agent_token: headers["Authorization"] = f"Bearer {agent_token}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return types.Part.from_bytes(data=r.content, mime_type="image/jpeg"), 200
        return None, r.status_code
    except: return None, 500

def try_update_agent_api(property_id: int, payload: dict, force_arnon: bool = False) -> str:
    if force_arnon:
        api_arnon = APIService()
        if api_arnon.authenticate(use_arnon=True):
            if api_arnon.update_property(str(property_id), payload):
                return "arnon"
        return ""

    api_primary = APIService()
    api_primary.authenticate()
    if api_primary.update_property(str(property_id), payload):
        return "primary"
    
    api_arnon = APIService()
    if api_arnon.authenticate(use_arnon=True):
        if api_arnon.update_property(str(property_id), payload):
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
    headers = api._get_auth_headers()
    is_arnon_fallback = False
    prop_type_name = "Unknown"
    is_condo = False
    existing_specs = {}

    try:
        r_prop = requests.get(f"{base_url}/api/agent/properties/{property_id}", headers=headers, timeout=15)
        r_prop.raise_for_status()
        prop_data = r_prop.json().get('data', {})
        
        # Check Owner Email
        owner_email = prop_data.get("owner", {}).get("email", "").lower()
        arnon_email = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
        is_arnon_owner = (owner_email == arnon_email)

        if is_arnon_owner and api.email != arnon_email:
            logger.info(f"🎯 Switching to Arnon for Property {property_id}")
            if api.authenticate(use_arnon=True):
                is_arnon_fallback = True
                headers = api._get_auth_headers()
                # Re-fetch with Arnon token
                r_prop = requests.get(f"{base_url}/api/agent/properties/{property_id}", headers=headers, timeout=15)
                prop_data = r_prop.json().get('data', {})
        
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
    refreshed = api.refresh_photo_urls(img_ids)
    url_map = {str(item.get("id")): item.get("url") for item in (refreshed.get("refreshed_images", []) if refreshed else [])}
    
    image_parts, original_image_ids = [], []
    for img_meta in gallery_images[:15]:
        img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("url")
        part, _ = download_image_as_part(img_url, agent_token=api.token)
        if part:
            image_parts.append(part)
            original_image_ids.append(str(img_meta.get("id")))
    
    if not image_parts: return

    # 3. Gemini Analysis (True Color Logic)
    prompt = (
        "Analyze these images to provide a TRUE area-based color and composition summary. "
        "Build a mental spatial map of the entire property rooms shown. "
        "1. 'total_color_composition': Provide a 14-integer array (sum 100) representing the TOTAL area percentage of each color (Walls + Floors + Doors + Ceilings + ALL Furniture). "
        "2. 'area_breakdown': Estimate area percentage for: 'walls', 'floors', 'doors', 'ceilings', 'furniture' (sum 100).\n"
        "3. 'furniture_details': List each furniture item and its 'area_percentage' relative to the total combined area.\n"
        "4. LIGHTING COMPENSATION: Identify ACTUAL material colors. NO lighting/reflection reports."
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[prompt] + image_parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PropertyAnalysisTrueColor
            )
        )
        res = response.parsed
        
        # Calculate dominant color
        max_idx = res.total_color_composition.index(max(res.total_color_composition))
        house_color = ENGLISH_COLORS[max_idx]
        house_color_thai = THAI_COLORS[max_idx]

        # 4. Update Agent API
        specs_payload = {
            "style": res.architect_style,
            "house_color": house_color,
            "color": house_color_thai,
            "true_color_composition": res.total_color_composition,
            "area_breakdown": res.area_breakdown
        }
        for k in ["floors", "bedrooms", "bathrooms"]:
            if existing_specs.get(k): specs_payload[k] = existing_specs[k]

        agent_payload = {"specifications": specs_payload, "specs": specs_payload, "house_color": house_color}
        used_acc = try_update_agent_api(property_id, agent_payload, force_arnon=is_arnon_owner)

        # 5. Save to Firestore
        now_iso = (datetime.utcnow() + timedelta(hours=7)).isoformat() + "Z"
        fs_payload = res.model_dump()
        fs_payload.update({
            "property_id": int(property_id),
            "house_color": house_color,
            "analyzed_at": now_iso,
            "true_color_analyzed": True
        })
        target_coll = "ARNON_properties_true_color" if used_acc == "arnon" else FIRESTORE_COLLECTION
        fs.db.collection(target_coll).document(str(property_id)).set(fs_payload, merge=True)
        
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
