import os
import requests
import json
import time
from io import BytesIO
from PIL import Image
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
TARGET_COLLECTION = "area_color" 
PROJECT_LIMIT = None  
TEST_PROPERTY_ID = None # 🛠️ ใส่ Property ID ที่ต้องการทดสอบที่นี่ (หรือใส่ None เพื่อรันปกติ)

# 14 Colors Mapping (Order matches logic)
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

# --- Schema สำหรับ True Color Analysis ---
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
    poor_condition_image_indices: List[int] = Field(description="Indices of images showing severe damage or hoarding.")

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
            img.save(buffer, format="WEBP", quality=80)
            return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/webp"), 200
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
                img.save(buffer, format="WEBP", quality=80)
                return types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/webp"), 200
        return None, r.status_code
    except Exception as e:
        print(f"      [!] Error downloading image ({url}): {e}")
        return None, 500

def main():
    api = APIService()
    api.authenticate()
    fs = FirestoreService()
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY_COLOR"))
    
    if TEST_PROPERTY_ID:
        print(f"🧪 Test Mode: Processing only Property ID {TEST_PROPERTY_ID}")
        doc_snap = fs.db.collection(TARGET_COLLECTION).document(str(TEST_PROPERTY_ID)).get()
        if not doc_snap.exists:
            # Fallback เผื่อหาในหมวดเดิม
            doc_snap = fs.db.collection("Leads").document(str(TEST_PROPERTY_ID)).get()
            
        if not doc_snap.exists:
            print(f"❌ Property {TEST_PROPERTY_ID} not found in Firestore.")
            return
        docs = [doc_snap]
    else:
        print(f"🚀 Starting True Color Analysis for up to {PROJECT_LIMIT} properties from '{TARGET_COLLECTION}'...")
        raw_docs = fs.db.collection(TARGET_COLLECTION).limit(PROJECT_LIMIT).stream()
        docs = list(raw_docs)  # โหลดทั้งหมดเข้า Memory ก่อนเพื่อป้องกัน Timeout (504)
        print(f"📦 Successfully fetched {len(docs)} properties into memory.")
    
    TARGET_IDS = ['1094', '1035']

    for doc in docs:
        prop_id = doc.id
        
        # 🔥 กรองเฉพาะ 50 รายการที่สุดโต่งเพื่อเทส 2.5 Flash
        if prop_id not in TARGET_IDS:
            continue
            
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
        # 🔥 ปิดการเช็คข้ามชั่วคราวเพื่อให้รันซ้ำ 50 ตัวท็อปได้
        # if data.get("true_color_analyzed") == True:
        #     print(f"⏭️ Skip {prop_id}: Already analyzed (true_color_analyzed=True)")
        #     continue

        print(f"\n🏠 Processing Property: {prop_id} (Account: {api.email})")
        
        # 1. Get Images from Firestore (Primary Source)
        images_info = data.get("images", []) or data.get("images_info", [])
        gallery_images = [img for img in images_info if img.get("tag") != "Common facilities"]
        
        # Fallback: ถ้าไม่มีรูปใน Firestore ให้ดึงจาก Agent API
        is_arnon_fallback = False
        if not gallery_images:
            print(f"      📡 No images in Firestore, fetching from Agent API...")
            headers = api._get_auth_headers()
            base_url = api.base_url.rstrip('/')
            try:
                r_detail = requests.get(f"{base_url}/api/agent/properties/{prop_id}", headers=headers, timeout=10)
                if r_detail.status_code == 200:
                    p_data = r_detail.json().get("data", {})
                    api_images = p_data.get("images", [])
                    gallery_images = [img for img in api_images if img.get("tag") != "Common facilities"]
                    
                    # เช็ค owner เผื่อต้องสลับบัญชี
                    owner_email = p_data.get("owner", {}).get("email", "").lower()
                    arnon_email_env = (os.getenv("AGENT_ARNON_EMAIL") or "arnon@painpointtoday.com").lower()
                    if owner_email == arnon_email_env:
                        print(f"      🎯 Arnon Property. Switching account...")
                        if api.authenticate(use_arnon=True):
                            is_arnon_fallback = True
                else:
                    print(f"      ⚠️ API returned {r_detail.status_code}")
            except Exception as e:
                print(f"      ⚠️ API error: {e}")
        
        if not gallery_images:
            print(f"      ❌ No gallery images found for {prop_id}")
            continue
        
        prop_type_name = data.get("property_type", "Unknown")

        # 3. Refresh & Download
        print(f"      📸 Refreshing and downloading {len(gallery_images)} images...")
        img_ids = [img.get("id") for img in gallery_images if img.get("id")]
        refreshed = api.refresh_photo_urls(img_ids)
        url_map = {str(item.get("id")): item.get("url") for item in (refreshed.get("refreshed_images", []) if refreshed else [])}
        
        image_parts = []
        for img_meta in gallery_images[:15]:
            img_url = url_map.get(str(img_meta.get("id"))) or img_meta.get("validated_url") or img_meta.get("url")
            part, status = download_image_as_part(img_url, agent_token=api.token, base_url=api.base_url)
            
            # Fallback 403 (เหมือนไฟล์ arnon_step2_analyze_colors.py)
            if status == 403 and not is_arnon_fallback:
                if api.authenticate(use_arnon=True):
                    is_arnon_fallback = True
                    part, status = download_image_as_part(img_url, agent_token=api.token, base_url=api.base_url)

            if part:
                image_parts.append(part)
                
            # ⏳ ถ่วงเวลา 0.5 วินาทีต่อ 1 รูป ป้องกัน DNS Timeout (Socket Exhaustion)
            import time
            time.sleep(0.5)
        
        if not image_parts:
            print(f"      ❌ No images could be downloaded for {prop_id}")
            continue

        # 3. Analyze with NEW 100/100 Spatial Map Logic
        prompt = (
            "Build a 3D mental spatial map of this property based on all provided images.\n"
            "CRITICAL RULES:\n"
            "1. FOCUS on the ATMOSPHERIC and STRUCTURAL material colors (Walls, Floors). These define the property's dominant house color.\n"
            "2. DO NOT let white furniture, bed sheets, or white bathroom fixtures (toilets/tubs/sinks) bias the overall color towards 'White' if the walls/floors are warm tones (Cream, Beige, Light Brown, Light Yellow).\n"
            "3. If walls are Cream/Beige, ensure 'Light Brown' or 'Light Yellow' or 'Yellowish Brown' gets the highest percentage in structural_colors, NOT White.\n"
            "4. 'room_element_breakdown': Estimate physical area % of structural parts (must sum to 100): 'wall', 'floor', 'ceiling', 'door'.\n"
            "5. 'structural_colors': For EACH structural part, provide a 14-integer array (sum=100) representing TRUE material colors.\n"
            "6. 'furniture_color_composition': 14-integer array (sum=100) for Furniture ONLY.\n"
            "7. 'room_weight': Fraction 0.0-1.0 for room structures. 'furniture_weight': Fraction for furniture. Sum = 1.0.\n"
            "8. Color order: [0:Green, 1:Brown, 2:Red, 3:Dark Yellow, 4:Orange, 5:Purple, 6:Pink, 7:Light Yellow, 8:Yellowish Brown, 9:Light Brown, 10:White, 11:Gray, 12:Blue, 13:Black].\n"
            "9. NO lighting/reflection artifacts. Identify TRUE material colors.\n"
            "10. STRICTLY EXCLUDE electrical appliances (AC, TV, refrigerator, etc.).\n"
            "11. STRICTLY EXCLUDE nature, trees, plants, grass, and garden elements. Focus ONLY on the Building Facade and Man-made materials.\n"
            "12. TONE PRIORITY: If a material color is ambiguous between a warm tone (Cream, Beige, Light Brown) and a cool tone (Gray, White), PRIORITIZE the warm tone."
        )

        # Determine collection name for weight logic
        collection_name = SOURCE_COLLECTIONS[0] if 'SOURCE_COLLECTIONS' in globals() else "Unknown"

        try:
            res = None
            for attempt in range(3):
                # ใช้ gemini-2.5-flash, gemini-3.1-flash-lite-preview เป็นตัวหลัก ห้ามแก้!!!
                current_model = "gemini-2.5-flash" if attempt < 2 else "gemini-3.1-flash-lite-preview"
                try:
                    response = client.models.generate_content(
                        model=current_model,
                        contents=[prompt] + image_parts,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=PropertyAnalysisResponse,
                            temperature=0.1
                        )
                    )
                    res = response.parsed
                    if res: break
                except Exception as e:
                    err_msg = str(e)
                    if ("503" in err_msg or "UNAVAILABLE" in err_msg or "429" in err_msg) and attempt < 2:
                        wait = (attempt + 1) * 10
                        print(f"      ⚠️ Gemini overloaded. Retry in {wait}s... (attempt {attempt+1}/3)")
                        time.sleep(wait)
                    else:
                        raise e
            
            if not res: return False

            # 🔥 FORCE 50/50 for Launch_Properties as requested
            collection_name = SOURCE_COLLECTIONS[0] if 'SOURCE_COLLECTIONS' in globals() else "Unknown"
            if collection_name == "Launch_Properties":
                res.area_weight.room = 50.0
                res.area_weight.furniture = 50.0
            elif not res.area_weight or res.area_weight.room == 0:
                res.area_weight.room = 80.0
                res.area_weight.furniture = 20.0
                
            # Calculate overall dominant color based on Spatial Weights (already calculated by AI)
            room_weight = res.room_weight
            furn_weight = res.furniture_weight
            
            # 1. คำนวณ Room Score แบบปกติ (1:1:1:1 ตาม Breakdown) - ลอจิกเดียวกับ Report
            def safe_get(lst, idx):
                return lst[idx] if lst and idx < len(lst) else 0

            room_comp_floats = []
            for i in range(14):
                val = (
                    (safe_get(res.structural_colors.wall, i) * res.room_element_breakdown.wall / 100) + 
                    (safe_get(res.structural_colors.floor, i) * res.room_element_breakdown.floor / 100) +
                    (safe_get(res.structural_colors.ceiling, i) * res.room_element_breakdown.ceiling / 100) + 
                    (safe_get(res.structural_colors.door, i) * res.room_element_breakdown.door / 100)
                )
                room_comp_floats.append(round(val))
                
            # Normalize to strictly sum to 100
            diff = 100 - sum(room_comp_floats)
            if diff != 0:
                max_idx_room = room_comp_floats.index(max(room_comp_floats))
                room_comp_floats[max_idx_room] += diff
            
            # Compute House Color
            combined_composition = []
            for i in range(14):
                val = (room_comp_floats[i] * room_weight) + (res.furniture_color_composition[i] * furn_weight)
                combined_composition.append(val)
                
            # หาผู้ชนะจาก 14 สีตรงๆ (No Mapping)
            max_score = -1
            winner_idx = 10 # Default White
            for i, score in enumerate(combined_composition):
                if score > max_score:
                    max_score = score
                    winner_idx = i
                    
            house_color = ENGLISH_COLORS[winner_idx]
            house_color_thai = THAI_COLORS_MAP.get(house_color, "ขาว")
            
            # หา Runner up (House Color 2)
            sorted_scores = sorted(enumerate(combined_composition), key=lambda x: x[1], reverse=True)
            house_color2 = ENGLISH_COLORS[sorted_scores[1][0]] if len(sorted_scores) > 1 and sorted_scores[1][1] > 0 else None
            house_color2_thai = THAI_COLORS_MAP.get(house_color2) if house_color2 else None
            
            # Save to Firestore (use by_alias=True to keep "Dark Yellow" etc. instead of "Dark_Yellow")
            payload = res.model_dump(by_alias=True)
            payload.update({
                "property_id": int(prop_id),
                "property_type": prop_type_name,
                "room_color_composition": room_comp_floats, # Include computed overall room color
                "system_color_scores": {ENGLISH_COLORS[i]: combined_composition[i] for i in range(14)},
                "house_color": house_color,
                "house_color_thai": house_color_thai,
                "house_color2": house_color2,
                "house_color2_thai": house_color2_thai,
                "area_weight": {
                    "room": room_weight * 100,
                    "furniture": furn_weight * 100
                },
                "true_color_analyzed": True,
                "analyzed_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            })
            
            fs.db.collection(TARGET_COLLECTION).document(prop_id).set(payload, merge=True)
            print(f"      📊 System Scores: {sorted_sys_colors[:4]}")
            print(f"✅ Success! Dominant: {house_color} | Room Weight: {room_weight*100:.1f}% | Furniture Weight: {furn_weight*100:.1f}%")
            
        except Exception as e:
            print(f"❌ Analysis failed for {prop_id}: {e}")
            
        # ⏳ ถ่วงเวลาพักให้ระบบ 2 วินาทีก่อนขึ้นบ้านหลังใหม่
        time.sleep(2)
        
        # Reset to Primary for next loop
        if is_arnon_fallback: api.authenticate(use_arnon=False)

if __name__ == "__main__":
    main()
