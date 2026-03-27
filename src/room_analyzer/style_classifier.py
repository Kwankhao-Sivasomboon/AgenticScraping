import os
import time
from typing import List, Dict, Any, Optional
from io import BytesIO
import requests
from PIL import Image
import imagehash
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

load_dotenv()

class PropertyImagesAnalysis(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra='ignore' # ถ้า AI ตอบเกินมาให้ข้ามไป ไม่ต้อง Error
    )
    average_color_hex: str = Field(description="HEX code of the overall dominant room color, e.g. #FFFFFF (Left for backward compatibility, you can put any hex here)")
    color: str = Field(description="The single overall dominant color of the property with the highest percentage. Must be one of the predefined list colors in Thai.")
    room_color: List[int] = Field(description="List of 14 integers summing to 100, representing color percentages in order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    element_color: List[int] = Field(description="List of 14 integers summing to 100, representing element color percentages in the same 14-color order.")
    element_furniture: List[List[str]] = Field(description="List of 14 lists of strings. Each sublist contains the names of furniture/appliances in that exact color in the same 14-color order. If a color has 0%, its sublist should be empty [].")
    interior_style: str = Field(description="Interior style: one of Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other")
    property_type: str = Field(description="Property type: one of 'condo', 'house', 'unknown' based on structural cues")
    valid_image_indices: List[int] = Field(description="List of integer indices (0-based) of images that show MAIN property features: INTERIOR rooms (bedroom, living room, kitchen, bathroom) or EXTERIOR of the actual house. Exclude: maps, floor plans, people, animals, blurry images.")
    secondary_image_indices: List[int] = Field(description="List of integer indices (0-based) of images that are VALID but NOT main features: Facilities, Swimming Pool, Gym, Lobby, or Corridor. Still exclude maps/junk.")


def download_image(url: str, retries=2) -> Optional[Image.Image]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
        "Referer": "https://www.livinginsider.com/",
        "Connection": "keep-alive"
    }
    
    for attempt in range(retries):
        try:
            # เพิ่ม delay นิดหน่อยเพื่อไม่ให้เซิร์ฟเวอร์โดนยิงรัวเกินไป
            if attempt > 0:
                time.sleep(1.5)
                
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.thumbnail((800, 800))
                return img
        except Exception as e:
            if attempt == retries - 1:
                print(f"    [X] Download Error on attempt {attempt+1}: {e}")
    return None

def filter_similar_images(image_data_list: List[Dict[str, Any]], threshold: int = 5):
    """
    กรองภาพที่คล้ายกันมากออก โดยใช้ Image Hashing
    """
    unique_data = []
    hashes = []
    
    for item in image_data_list:
        img = item['img']
        current_hash = imagehash.phash(img)
        
        is_duplicate = False
        for h in hashes:
            if current_hash - h < threshold:
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_data.append(item)
            hashes.append(current_hash)
            
    return unique_data

def analyze_room_images(image_urls: List[str]) -> Optional[PropertyImagesAnalysis]:
    api_key = os.getenv("GEMINI_API_KEY_COLOR") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[!] Warning: No Gemini API Key found (GEMINI_API_KEY_COLOR / GEMINI_API_KEY / GOOGLE_API_KEY). Skipping image analysis.")
        return None
    key_source = "GEMINI_API_KEY_COLOR" if os.getenv("GEMINI_API_KEY_COLOR") else ("GEMINI_API_KEY" if os.getenv("GEMINI_API_KEY") else "GOOGLE_API_KEY")
    print(f"  [AI] Using key from: {key_source}")

        
    client = genai.Client(api_key=api_key)
    
    # ดาวน์โหลดรูปภาพเก็บเป็น List ของ ข้อมูล
    downloaded_data = []
    for i, u in enumerate(image_urls):
        # สุ่ม sleep สั้นๆ ระหว่างรูปเพื่อกันโดนบล็อก (เพิ่ม delay ขึ้นอีกเพื่อความปลอดภัยยิ่งขึ้น)
        import random
        time.sleep(random.uniform(1.5, 3.5))
        img = download_image(u)
        if img: 
            downloaded_data.append({"img": img, "url": u, "original_index": i})
        else:
            print(f"  [X] Failed to download index {i}")
            
    if not downloaded_data:
        return None

    # กรองภาพซ้ำ/คล้ายกัน (Deduplication) เพื่อลด context window ที่ส่งไปให้ Gemini
    unique_data = filter_similar_images(downloaded_data)
    if len(unique_data) < len(downloaded_data):
        print(f"  [AI] Filtered out {len(downloaded_data) - len(unique_data)} duplicate/similar images before AI analysis.")

    pil_images = [item['img'] for item in unique_data]
    original_indices = [item['original_index'] for item in unique_data]

    prompt = (
        "Analyze these property images. "
        "IMPORTANT INSTRUCTIONS:\n"
        "1. Identify valid images and categorize them into two lists:\n"
        "   - 'valid_image_indices': ONLY include images that show MAIN property features: INTERIOR rooms (bedroom, living room, kitchen, bathroom) or EXTERIOR of the actual house/building.\n"
        "   - 'secondary_image_indices': Include images that are VALID but NOT main features: Facilities, Swimming Pool, Gym, Fitness center, Lobby, Corridor, or nice building surroundings. Still exclude junk.\n"
        "   - IGNORE and skip any images that show ONLY: maps, floor plans, blueprints, purely text-based ads/Line ID cards, people/animals, or completely blurry/irrelevant images.\n"
        "2. List the indices (0-based) based on the criteria above.\n"
        "3. Analyze colors of Wall, Door, and Furniture from the MAIN images and provide overall dominant 'color' in Thai.\n"
        "4. YOU MUST evaluate exactly 14 colors in this STRICT order for 'room_color' and 'element_color':\n"
        "   1. Green, 2. Brown, 3. Red, 4. Dark Yellow, 5. Orange, 6. Purple, 7. Pink, 8. Light Yellow, 9. Yellowish Brown, 10. Light Brown, 11. White, 12. Gray, 13. Blue, 14. Black\n"
        "5. Provide 'room_color' and 'element_color' as JSON arrays of 14 integers summing exactly to 100.\n"
        "6. For 'element_furniture': YOU MUST list ALL furniture and objects you can see in ALL the images. "
        "   For each item, place it under the color index that BEST matches its dominant color. "
        "   Be GENEROUS and inclusive — if you see a bed, sofa, wardrobe, table, chair, mirror, lamp, curtain, or any other object, list it. "
        "   Do NOT leave sub-arrays empty if there are any items of that color in the room. "
        "   Example: White bed → index 10 (White), Dark brown cabinet → index 9 (Light Brown) or 1 (Brown). "
        "   The result must be an array of exactly 14 sub-arrays. Each sub-array contains English names of items.\n"
        "7. Categorize the Interior Design Style: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
        "8. Categorize the property_type: 'condo', 'house', or 'unknown'."
    )

    contents = [prompt]
    for orig_idx, img in zip(original_indices, pil_images):
        contents.append(f"Image Index: {orig_idx}")
        contents.append(img)
        
    print(f"  [AI] Sending {len(pil_images)} images to Gemini for analysis (Color, Style, Filtering)...")
    
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash', # โมเดลเดิม
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PropertyImagesAnalysis,
                    temperature=0.1
                )
            )
            analysis_data = response.text
            try:
                result = PropertyImagesAnalysis.model_validate_json(analysis_data)
                print(f"  [AI] Result Validated! Style: {result.interior_style}, Color: {result.color}, Images: {len(result.valid_image_indices)}")
                return result
            except Exception as ve:
                print(f"  [AI] JSON Validation Error: {ve}")
                print(f"  [AI] Raw Output: {analysis_data}")
                return None
        except Exception as e:
            if "503" in str(e) and attempt < 2:
                time.sleep((attempt + 1) * 3)
                continue
            print(f"  [AI] API Connection Error: {e}")
            return None
            
    return None
