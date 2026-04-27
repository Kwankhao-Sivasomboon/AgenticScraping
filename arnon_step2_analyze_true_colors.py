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
    area_percentage: float = Field(description="Percentage of the TOTAL property surface area this item occupies.")

class PropertyAnalysisTrueColor(BaseModel):
    architect_style: str = Field(description="Architectural or Interior style (Modern, Nordic, etc.)")
    
    # 🏠 Room Structure Colors (Sum 100)
    room_color_composition: List[int] = Field(description="14-color percentage (sum 100) for Walls, Floors, Doors, Ceilings ONLY.")
    
    # 🛋️ Furniture Colors (Sum 100)
    furniture_color_composition: List[int] = Field(description="14-color percentage (sum 100) for Furniture ONLY.")
    
    # 🎨 Furniture Elements Mapping (Dictionary of lists)
    # Keys must be the 14 English Colors (e.g., 'White', 'Gray', 'Black'...)
    furniture_elements: Dict[str, List[str]] = Field(description="Mapping of 14 English colors to lists of furniture names in that color (e.g. {'White': ['Table', 'Chair'], 'Black': ['TV']})")
    
    # Element Area Breakdown (Sum to 100)
    area_breakdown: Dict[str, float] = Field(description="Actual physical percentage of area occupied by: walls, floors, doors, ceilings, furniture. (SUM MUST BE 100)")
    
    # Detailed Furniture Breakdown
    furniture_details: List[FurnitureItem] = Field(description="List of every unique furniture item found and its area percentage relative to the TOTAL physical surface area.")
    
    raw_room_color: str = Field(description="Raw description of colors for Walls, Doors, Floors, Ceilings.")
    raw_furniture_color: str = Field(description="Raw description of colors for furniture items.")
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

        # 3. Analyze with NEW 100/100 Spatial Map Logic
        prompt = (
            "Build a 3D mental spatial map of this property based on all provided images. "
            "1. 'room_color_composition': Provide a 14-integer array (sum 100) representing the physical surface area percentage of Walls, Floors, Doors, and Ceilings ONLY. "
            "2. 'furniture_color_composition': Provide a 14-integer array (sum 100) representing the physical surface area percentage of Furniture ONLY. "
            "3. 'furniture_elements': A dictionary mapping the 14 English colors (e.g., 'White', 'Brown') to a list of unique furniture names found in that color. "
            "4. 'area_breakdown': Estimate the physical area percentage for: 'walls', 'floors', 'doors', 'ceilings', 'furniture'. SUM MUST BE 100.\n"
            "5. 'furniture_details': List unique furniture items and their area % relative to the TOTAL physical surface area.\n"
            "6. Color order for arrays: [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
            "7. NO lighting/reflection reporting. Identify TRUE material colors. Compensate for camera perspective."
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
            
            # Calculate overall dominant color based on Spatial Weights
            room_weight = (res.area_breakdown.get('walls', 0) + res.area_breakdown.get('floors', 0) + 
                           res.area_breakdown.get('doors', 0) + res.area_breakdown.get('ceilings', 0)) / 100
            furn_weight = res.area_breakdown.get('furniture', 0) / 100
            
            combined_composition = []
            for i in range(14):
                val = (res.room_color_composition[i] * room_weight) + (res.furniture_color_composition[i] * furn_weight)
                combined_composition.append(val)
                
            max_idx = combined_composition.index(max(combined_composition))
            house_color = ENGLISH_COLORS[max_idx]
            house_color_thai = THAI_COLORS[max_idx]
            
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
