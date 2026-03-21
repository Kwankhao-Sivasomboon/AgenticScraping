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
    color_name: str = Field(description="Color breakdown of the room in Thai, formatted exactly as: 'กำแพงออกโทนเป็นสี... (X%ของภาพทั้งหมด) , ประตูห้องสี...(Y%ของภาพ), เฟอร์นิเจอร์สี...+... (Z%+W% ตามลำดับ)'")
    interior_style: str = Field(description="Interior style: one of Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other")
    property_type: str = Field(description="Property type: one of 'condo', 'house', 'unknown' based on structural cues")
    valid_image_indices: List[int] = Field(description="List of integer indices (0-based) of images that show interior rooms. Exclude: maps, floor plans, people, animals, blurry images.")


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
        "1. Identify valid images. IGNORE and skip any images that show ONLY: floor plans/blueprints, maps (e.g. Google Maps), pure outdoor scenery with no building, swimming pool-only shots, people/animals, or completely blurry images. Images that have watermarks or overlaid text are still VALID if they show an interior or exterior of a property.\n"
        "2. List the 'valid_image_indices' which corresponds to the 'Image Index' labels provided for each image. ONLY include indices of images that are VALID based on the criteria above.\n"
        "3. From the valid images, analyze the colors of the Wall, Door, and Furniture. Provide your breakdown in the 'color_name' field strictly in Thai. The string MUST conform EXACTLY to this structural format:\n"
        "   'กำแพงออกโทนเป็นสีขาว (60%ของภาพทั้งหมด) , ประตูห้องสีน้ำตาล(20%ของภาพ), เฟอร์นิเจอร์สีดำ+เขียว+ชมพู(5%+5%+10% ตามลำดับ)'\n"
        "   You MUST ONLY use colors from this predefined list for your descriptions. NEVER use other external color names. DO NOT write the elements (Wood, Fire, etc), ONLY write these colors:\n"
        "   - สีเขียว, สีน้ำตาล\n"
        "   - สีแดง, สีเหลืองเข้ม, สีส้ม, สีม่วง, สีชมพู\n"
        "   - สีเหลืองอ่อน, สีเหลืองปนน้ำตาล, สีน้ำตาลอ่อน\n"
        "   - สีขาว, สีเทา\n"
        "   - สีน้ำเงิน, สีดำ\n"
        "4. Categorize the Interior Design Style into EXACTLY ONE of these styles: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
        "5. Categorize the property_type as either 'condo', 'house', or 'unknown' based on clues like exterior views, ceiling height, or balconies."
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
                print(f"  [AI] Result Validated! Style: {result.interior_style}, Color: {result.color_name}, Images: {len(result.valid_image_indices)}")
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
