import os
import requests
import json
import time
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from dotenv import load_dotenv
from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

# Load environment
load_dotenv()

# Config
TARGET_COLLECTION = "arnon_properties_true_color" # แยกคอลเลกชันใหม่
PROJECT_LIMIT = 500  # ปรับได้ตามความเหมาะสม

# 14 Colors Mapping (Order matches logic)
ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]
THAI_COLORS = [
    "เขียว", "น้ำตาล", "แดง", "เหลืองเข้ม", "ส้ม", "ม่วง", "ชมพู",
    "เหลืองอ่อน", "น้ำตาลอมเหลือง", "น้ำตาลอ่อน", "ขาว", "เทา", "น้ำเงิน", "ดำ"
]

# --- Schema สำหรับ True Color Analysis ---
class FurnitureItem(BaseModel):
    name: str = Field(description="Name of the furniture item (English)")
    area_percentage: float = Field(description="Percentage of the TOTAL image area this item occupies.")

class PropertyAnalysisTrueColor(BaseModel):
    architect_style: str = Field(description="Architectural or Interior style (Modern, Nordic, etc.)")
    raw_room_color: str = Field(description="Raw description of colors for Walls, Doors, Floors, Ceilings.")
    raw_furniture_color: str = Field(description="Raw description of colors for each unique furniture item.")
    
    # 100% Composition Analysis
    total_color_composition: List[int] = Field(description="Aggregated 14-color percentage (sum 100) including EVERYTHING (Room + Furniture).")
    
    # Element Area Breakdown (Sum to 100)
    area_breakdown: Dict[str, float] = Field(description="Percentage of area occupied by: walls, floors, doors, ceilings, furniture. (e.g. {'walls': 40, 'floors': 30, 'doors': 5, 'ceilings': 20, 'furniture': 5})")
    
    # Detailed Furniture Breakdown
    furniture_details: List[FurnitureItem] = Field(description="List of each unique furniture item found and its area percentage relative to the total image area.")
    
    poor_condition_image_indices: List[int] = Field(description="Indices of images showing severe damage or hoarding.")

def download_image_as_part(url: str, agent_token: str = None):
    headers = {"User-Agent": "Mozilla/5.0"}
    if agent_token:
        headers["Authorization"] = f"Bearer {agent_token}"
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return types.Part.from_bytes(data=r.content, mime_type="image/jpeg"), 200
        return None, r.status_code
    except Exception as e:
        print(f"      [!] Error downloading image: {e}")
        return None, 500

def main():
    api = APIService()
    api.authenticate()
    fs = FirestoreService()
    
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_COLOR"))
    
    # ดึงข้อมูลจาก Leads ที่มีรูปและยังไม่ได้วิเคราะห์แบบ True Color
    docs = fs.db.collection("Leads").where("analyzed", "==", True).limit(PROJECT_LIMIT).stream()
    
    print(f"🚀 Starting True Color Analysis for up to {PROJECT_LIMIT} properties...")
    
    for doc in docs:
        prop_id = doc.id
        data = doc.to_dict()
        
        # เช็คว่าเคยรัน True Color ไปหรือยัง (กันรันซ้ำ)
        if data.get("true_color_analyzed"):
            continue

        print(f"\n🏠 Processing Property: {prop_id}")
        
        images_info = data.get("images_info", [])
        if not images_info: continue
        
        gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]
        if not gallery_images: continue

        # 1. เช็คเจ้าของก่อน (Proactive Switch)
        headers = api._get_auth_headers()
        base_url = api.base_url.rstrip('/')
        is_arnon_fallback = False
        prop_type_name = "Unknown"
        
        try:
            r_detail = requests.get(f"{base_url}/api/agent/properties/{prop_id}", headers=headers, timeout=10)
            if r_detail.status_code == 200:
                p_data = r_detail.json().get("data", {})
                owner_email = p_data.get("owner", {}).get("email", "").lower()
                arnon_email_env = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
                is_arnon_owner = (owner_email == arnon_email_env)
                
                if is_arnon_owner:
                    print(f"      🎯 Arnon Property. Switching account...")
                    if api.authenticate(use_arnon=True):
                        is_arnon_fallback = True
                prop_type_name = p_data.get("property_type", {}).get("name", "Unknown")
        except: pass

        # 2. Refresh & Download
        img_ids = [img.get("id") for img in gallery_images if img.get("id")]
        refreshed = api.refresh_photo_urls(img_ids)
        url_map = {str(item.get("id")): item.get("url") for item in (refreshed.get("refreshed_images", []) if refreshed else [])}
        
        image_parts = []
        original_image_ids = []
        for img_meta in gallery_images[:15]:
            img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("url")
            part, status = download_image_as_part(img_url, agent_token=api.token)
            if part:
                image_parts.append(part)
                original_image_ids.append(str(img_meta.get("id")))
        
        if not image_parts: continue

        # 3. Analyze with NEW Logic (Spatial Map / Floor Plan Perspective)
        prompt = (
            "Build a 3D mental spatial map of this property based on all provided images. "
            "1. 'total_color_composition': Provide a 14-integer array (sum 100) representing the TRUE PHYSICAL SURFACE AREA percentage for each color across the entire property (including all Walls, Floors, Doors, Ceilings, and Furniture). "
            "Color order: [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
            "2. 'area_breakdown': Estimate the actual physical area percentage covered by: 'walls', 'floors', 'doors', 'ceilings', 'furniture'. These MUST sum to exactly 100% of the property's physical surfaces.\n"
            "3. 'furniture_details': List EVERY unique furniture element found. For each, estimate its 'area_percentage' relative to the TOTAL physical surface area of the property.\n"
            "4. 'architect_style': Choose ONE: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
            "5. 'raw_room_color' & 'raw_furniture_color': Detailed descriptive strings of materials and colors as they exist in the 3D space.\n"
            "6. COMPENSATE FOR PERSPECTIVE: Do not be fooled by camera angles or distance. Estimate the actual surface area as if you were measuring the room with a tool. NO lighting/reflection reporting."
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
            
            # Save to Firestore
            payload = res.model_dump()
            payload.update({
                "property_id": int(prop_id),
                "property_type": prop_type_name,
                "house_color": house_color,
                "true_color_analyzed": True,
                "analyzed_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            })
            
            fs.db.collection(TARGET_COLLECTION).document(prop_id).set(payload)
            print(f"✅ Success! Dominant: {house_color} | Walls: {res.area_breakdown.get('walls')}% | Furniture: {res.area_breakdown.get('furniture')}%")
            
        except Exception as e:
            print(f"❌ Analysis failed for {prop_id}: {e}")
        
        # Reset to Primary for next loop
        if is_arnon_fallback: api.authenticate(use_arnon=False)

if __name__ == "__main__":
    main()
