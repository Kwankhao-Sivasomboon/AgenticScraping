import os
import time
from typing import List, Dict, Any, Optional
from io import BytesIO
import requests
from PIL import Image
import imagehash
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

class InteriorStyle(str, Enum):
    MODERN = "Modern"
    NORDIC = "Nordic"
    CONTEMPORARY = "Contemporary"
    MINIMALIST = "Minimalist"
    LOFT = "Loft"
    LUXURY = "Luxury"
    OTHER = "Other"

class PropertyType(str, Enum):
    CONDO = "condo"
    HOUSE = "house"
    UNKNOWN = "unknown"

class PropertyImagesAnalysis(BaseModel):
    average_color_hex: str = Field(description="HEX code of the overall dominant room color")
    color_name: str = Field(description="Color name of the overall dominant room color (e.g. White, Beige, Gray)")
    interior_style: InteriorStyle = Field(description="Interior style of the rooms")
    property_type: PropertyType = Field(description="Is the property a condo or a house? Determine from structural cues (e.g. detached building = house, high rise = condo).")
    valid_image_indices: List[int] = Field(description="Indices (starting from 0) of the images that are relevant AND NOT maps, floor plans, people, or unrelated objects. Must be integers matching the input array order.")

def download_image(url: str) -> Optional[Image.Image]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((800, 800))
            return img
    except Exception as e:
        print(f"    [X] Download Error: {e}")
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
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[!] Warning: GEMINI_API_KEY is not set.")
        return None
        
    client = genai.Client(api_key=api_key)
    
    # ดาวน์โหลดรูปภาพเก็บเป็น List ของ ข้อมูล
    downloaded_data = []
    for i, u in enumerate(image_urls):
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
        "1. Identify valid images. IGNORE and skip any images that contain animals, people, blurry content, floor plans, blueprints, maps (Google Maps), or swimming pools. Focus ONLY on the architectural structure, walls, dominant furniture, and design elements.\n"
        "2. List the 'valid_image_indices' which corresponds to the 'Image Index' labels provided for each image. ONLY include indices of images that are VALID based on the criteria above.\n"
        "3. From the valid images, extract the Average Dominant Color (HEX) and color_name (e.g., White, Cream, Gray).\n"
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
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PropertyImagesAnalysis,
                    temperature=0.1
                )
            )
            analysis_data = response.text
            return PropertyImagesAnalysis.model_validate_json(analysis_data)
        except Exception as e:
            if "503" in str(e) and attempt < 2:
                time.sleep((attempt + 1) * 3)
                continue
            print(f"  [!] AI API Error: {e}")
            return None
            
    return None
