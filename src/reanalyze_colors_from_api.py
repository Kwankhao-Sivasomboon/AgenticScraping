import os
import sys
import time
import datetime
import json
from typing import List, Dict, Any
from io import BytesIO
import requests
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from google.cloud import firestore as google_firestore
from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

class PropertyColorAnalysis(BaseModel):
    color: str = Field(description="The single overall dominant color of the property with the highest percentage. Must be one of the predefined list colors in Thai.")
    interior_style: str = Field(description="Interior style: one of Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other")
    room_color: List[int] = Field(description="List of 14 integers summing to 100, representing color percentages in order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    element_color: List[int] = Field(description="List of 14 integers summing to 100, representing element color percentages in the same 14-color order.")
    element_furniture: List[List[str]] = Field(description="List of 14 lists of strings. Each sublist contains the names of furniture/appliances in that exact color in the same 14-color order. If a color has 0%, its sublist should be empty [].")

def download_image(url: str, retries=2) -> Image.Image | None:
    # เพิ่ม User-Agent เพื่อเลี่ยง 403 (บาง Server จะ Block ถ้าไม่มี Header)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                if img.mode != "RGB": img = img.convert("RGB")
                img.thumbnail((800, 800)) 
                return img
            elif r.status_code == 403:
                if attempt < retries - 1:
                    time.sleep(1)
                else:
                    print(f"❌ HTTP 403 Forbidden for: {str(url)[:100]}...")
            else:
                if attempt == retries - 1:
                    print(f"❌ HTTP {r.status_code} for URL: {str(url)[:100]}...")
        except Exception as e:
            if attempt == retries - 1:
                print(f"❌ Failed to download {str(url)[:60]}...: {e}")
    return None

def analyze_overall_colors(image_urls: List[str]) -> PropertyColorAnalysis | None:
    api_key = os.getenv("GEMINI_API_KEY_COLOR") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return None
    client = genai.Client(api_key=api_key)

    pil_images = []
    print(f"📥 Downloading ({len(image_urls)}) images concurrently for AI Analysis...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(download_image, image_urls))
        for img in results:
            if img:
                pil_images.append(img)
            
    if not pil_images:
        print("❌ No images could be downloaded. Skipping.")
        return None

    prompt = (
        "Analyze the interior colors shown across ALL these images combined.\n"
        "1. Identify the predominant Interior Design Style ('interior_style') into EXACTLY ONE: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other.\n"
        "2. Provide ONE overall dominant 'color' for the property using ONLY the following predefined list of Thai color names: สีเขียว, สีน้ำตาล, สีแดง, สีเหลืองเข้ม, สีส้ม, สีม่วง, สีชมพู, สีเหลืองอ่อน, สีเหลืองปนน้ำตาล, สีน้ำตาลอ่อน, สีขาว, สีเทา, สีน้ำเงิน, สีดำ\n"
        "3. YOU MUST evaluate exactly 14 colors in this STRICT order for 'room_color' and 'element_color':\n"
        "   1. Green, 2. Brown, 3. Red, 4. Dark Yellow, 5. Orange, 6. Purple, 7. Pink, 8. Light Yellow, 9. Yellowish Brown, 10. Light Brown, 11. White, 12. Gray, 13. Blue, 14. Black\n"
        "4. Provide 'room_color' as a JSON array of 14 integers summing exactly to 100. (For Walls, Floors, Ceilings, room doors).\n"
        "5. Provide 'element_color' as a JSON array of 14 integers summing exactly to 100. (For Furniture, Appliances, Decorations).\n"
        "6. Provide 'element_furniture' as an array of 14 sub-arrays. Each sub-array contains the English names of items in that color index."
    )

    contents = [prompt] + pil_images
    print(f"🧠 Sending {len(pil_images)} images to Gemini for analysis...")
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PropertyColorAnalysis,
                temperature=0.1
            )
        )
        return PropertyColorAnalysis.model_validate_json(response.text)
    except Exception as e:
        print(f"❌ Error during Gemini evaluation: {e}")
        return None

def run_workflow(property_id: int):
    api = APIService()
    fs_service = FirestoreService()
    
    # --- Phase 0: ดึงข้อมูลเดิมจาก Firestore ก่อน ---
    docs = fs_service.db.collection(fs_service.collection_name).where(filter=google_firestore.FieldFilter("api_property_id", "==", int(property_id))).limit(1).get()
    
    doc_id = None
    raw_images_from_firestore = []
    for d in docs:
        doc_id = d.id
        raw_images_from_firestore = d.to_dict().get("images", [])
        break

    print(f"\n🚀 Phase 1: Fetching Status for Property {property_id} from API")
    property_data = api.get_property_status(property_id)
    images_data = property_data.get("images", []) if property_data else []
    
    valid_urls = []
    
    # พยายามใช้ API Refresh ก่อน
    if images_data:
        image_ids = [img["id"] for img in images_data]
        print(f"✅ Found {len(image_ids)} images in API. Refreshing Signed URLs...")
        refreshed_data = api.refresh_photo_urls(image_ids)
        
        images_to_process = []
        if isinstance(refreshed_data, list):
            images_to_process = refreshed_data
        elif isinstance(refreshed_data, dict) and "refreshed_images" in refreshed_data:
            images_to_process = refreshed_data["refreshed_images"]

        if images_to_process:
            for img in images_to_process:
                url = img.get("url") or img.get("test_link") if isinstance(img, dict) else img
                if url:
                    if str(url).startswith("southeast"): url = "https://" + str(url)
                    valid_urls.append(url)
    
    # ถ้า API ไม่มีรูป ให้ Fallback ไป Firestore
    if not valid_urls and raw_images_from_firestore:
        print(f"⚠️ API has no usable images. Falling back to Firestore 'images'.")
        for url in raw_images_from_firestore:
            if url:
                if str(url).startswith("southeast"): url = "https://" + str(url)
                valid_urls.append(url)

    if not valid_urls:
         print("❌ No valid URLs found even after all fallbacks.")
         return

    print(f"✅ Ready to analyze {len(valid_urls)} URLs.")
    color_result = analyze_overall_colors(valid_urls)
    
    if not color_result:
        print("❌ Color analysis failed.")
        return
        
    print(f"🎯 Final Color Output:\nRoom: {color_result.room_color}\nElement: {color_result.element_color}")
    
    print(f"\n🚀 Phase 4: Saving Color Output to Firestore (Skipped API Submission)")
    if doc_id:
        furniture_storage = [", ".join(items) if items else "" for items in color_result.element_furniture]
        fs_service.db.collection(fs_service.collection_name).document(doc_id).update({
            "color": color_result.color,
            "interior_style": color_result.interior_style,
            "room_color": color_result.room_color,
            "element_color": color_result.element_color,
            "element_furniture": furniture_storage,
            "last_color_analysis_at": datetime.datetime.now()
        })
        print(f"✅ Saved results to Firestore for Document: {doc_id}")
    else:
        print(f"❌ Cannot save: No Firestore document found for api_id={property_id}")

def run_all_workflow(limit: int = 0, start_after_id: int = 0, max_id: int = 999999):
    fs_service = FirestoreService()
    print(f"📡 Fetching properties from Firestore starting after ID {start_after_id}...")
    
    query = fs_service.db.collection(fs_service.collection_name).where(filter=google_firestore.FieldFilter("api_property_id", ">", start_after_id)).order_by("api_property_id")
    if limit > 0: query = query.limit(limit)
    
    docs_list = list(query.stream())
    
    items = []
    for d in docs_list:
        pid = int(d.get("api_property_id") or 0)
        if pid > max_id: continue
        items.append(pid)

    total = len(items)
    if total == 0:
        print(f"✅ Found 0 properties in range.")
        return
        
    for i, pid in enumerate(items):
        print(f"\n{'='*50}\n🔄 [{i+1}/{total}] Processing Property ID: {pid}\n{'='*50}")
        try:
            run_workflow(pid)
        except Exception as e:
            print(f"❌ Error with ID {pid}: {e}")
        time.sleep(2)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "resume" and len(sys.argv) > 2:
            run_all_workflow(start_after_id=int(sys.argv[2]))
        elif sys.argv[1].isdigit():
            run_workflow(int(sys.argv[1]))
        else:
            print("Usage: python reanalyze_colors_from_api.py resume <id>")
    else:
        print("Usage: python reanalyze_colors_from_api.py <id> OR resume <id>")
