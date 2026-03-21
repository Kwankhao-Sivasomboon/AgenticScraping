import os
import sys
import time
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

from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

class PropertyColorAnalysis(BaseModel):
    room_color: List[int] = Field(description="List of 14 integers summing to 100, representing color percentages in order: [Green, Brown, Red, Dark Yellow, Orange, Purple, Pink, Light Yellow, Yellowish Brown, Light Brown, White, Gray, Blue, Black]")
    element_color: List[int] = Field(description="List of 14 integers summing to 100, representing element color percentages in the same 14-color order.")
    element_furniture: List[List[str]] = Field(description="List of 14 lists of strings. Each sublist contains the names of furniture/appliances in that exact color in the same 14-color order. If a color has 0%, its sublist should be empty [].")

def download_image(url: str, retries=2) -> Image.Image | None:
    # ⚠️ ห้ามส่ง Header พิเศษเด็ดขาด เพราะ Signed URL ของ S3 ถูกเซ็นด้วยค่า Header ว่างๆ
    # ถ้าส่ง User-Agent เข้าไป Signature จะพังและโดน 403 Forbidden ทันที
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                img = Image.open(BytesIO(r.content))
                if img.mode != "RGB": img = img.convert("RGB")
                img.thumbnail((512, 512)) # ลดขนาดลงอีกเพื่อให้ประมวลผลเร็วขึ้น
                return img
            elif r.status_code == 403:
                # เกิดจากโดน S3 ปฏิเสธการเข้าถึง
                if attempt < retries - 1:
                    time.sleep(1)
                else:
                    print(f"❌ HTTP 403 Forbidden: S3 rejected our request. Content: {r.text[:100]}")
            else:
                if attempt == retries - 1:
                    print(f"❌ HTTP {r.status_code} for URL: {str(url)[:100]}...")
        except Exception as e:
            if attempt == retries - 1:
                # Use str() to satisfy linter just in case
                url_snippet = str(url)[:60]
                print(f"❌ Failed to download {url_snippet}...: {e}")
    return None

def analyze_overall_colors(image_urls: List[str]) -> PropertyColorAnalysis | None:
    api_key = os.getenv("GEMINI_API_KEY_COLOR") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return None
    client = genai.Client(api_key=api_key)

    pil_images = []
    print(f"📥 Downloading ({len(image_urls)}) images concurrently for AI Analysis...")
    start_dl = time.time()
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        # ใช้ map เพื่อดึงความเร็วของการขนาน
        results = list(executor.map(download_image, image_urls))
        for img in results:
            if img:
                pil_images.append(img)
            
    print(f"✅ Downloaded {len(pil_images)} images in {time.time() - start_dl:.2f} seconds.")
    
    if not pil_images:
        print("❌ No images could be downloaded. Skipping.")
        return None

    prompt = (
        "Analyze the interior colors shown across ALL these images combined.\n"
        "1. You MUST evaluate exactly 14 colors in this STRICT order:\n"
        "   1. Green\n"
        "   2. Brown\n"
        "   3. Red\n"
        "   4. Dark Yellow\n"
        "   5. Orange\n"
        "   6. Purple\n"
        "   7. Pink\n"
        "   8. Light Yellow\n"
        "   9. Yellowish Brown\n"
        "   10. Light Brown\n"
        "   11. White\n"
        "   12. Gray\n"
        "   13. Blue\n"
        "   14. Black\n"
        "2. Provide 'room_color' as a JSON array of 14 integers summing exactly to 100. (For Walls, Floors, Ceilings, room doors).\n"
        "3. Provide 'element_color' as a JSON array of 14 integers summing exactly to 100. (For Furniture, Appliances, Decorations).\n"
        "4. Provide 'element_furniture' as a JSON array of 14 sub-arrays. Each sub-array contains the English names of specific items corresponding to that color index. Use an empty sub-array [] if the color is 0%.\n"
        "5. CRITICAL: Do NOT classify large wooden built-in surfaces like Wardrobes, Closets, or Kitchen Cabinets as 'room_color'. They MUST remain as 'element_color'.\n"
        "Example Output format (MUST be strictly valid JSON and length of array MUST exactly be 14):\n"
        "{\n"
        "  \"room_color\": [0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 80, 15, 0, 0],\n"
        "  \"element_color\": [0, 25, 0, 0, 0, 0, 0, 0, 0, 0, 60, 0, 0, 15],\n"
        "  \"element_furniture\": [[], [\"Bed\", \"Cabinet\"], [], [], [], [], [], [], [], [], [\"Washing Machine\", \"Sink\"], [], [], [\"Sofa\", \"TV\"]]\n"
        "}"
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
        result = PropertyColorAnalysis.model_validate_json(response.text)
        return result
    except Exception as e:
        print(f"❌ Error during Gemini evaluation: {e}")
        return None

def run_workflow(property_id: int):
    api = APIService()
    firestore = FirestoreService()
    
    print(f"\n🚀 Phase 1: Fetching Status for Property {property_id}")
    property_data = api.get_property_status(property_id)
    if not property_data:
        print("❌ Could not get property data.")
        return

    images_data = property_data.get("images", [])
    image_ids = [img["id"] for img in images_data]
    
    if not image_ids:
        print("ℹ️ No images found for this property.")
        return
        
    print(f"✅ Found {len(image_ids)} images.")
    
    print(f"\n🔄 Phase 2: Refreshing Signed URLs (Requesting fresh signatures)")
    refreshed_data = api.refresh_photo_urls(image_ids)
    
    valid_urls = []
    # ปรับปรุงการดึงรูปภาพจาก Refresh Response: รองรับทั้ง List และ Dict {"refreshed_images": [...]}
    images_to_process = []
    if isinstance(refreshed_data, list):
        images_to_process = refreshed_data
    elif isinstance(refreshed_data, dict) and "refreshed_images" in refreshed_data:
        images_to_process = refreshed_data["refreshed_images"]

    if images_to_process:
        print(f"📡 Using {len(images_to_process)} fresh URLs from Refresh Response.")
        for img in images_to_process:
            if isinstance(img, dict):
                url = img.get("url") or img.get("test_link")

                if url:
                    if str(url).startswith("southeast"):
                        url = "https://" + str(url)
                    valid_urls.append(url)
            elif isinstance(img, str):
                valid_urls.append(img)
    
    # ถ้า Refresh ไม่ได้คืนลิ้งค์มา (หรือคืนมาว่าง) ให้ fallback ไปใช้ข้อมูลจาก Phase 1 (ดึง test_link ถ้ามี)
    if not valid_urls:
        print(f"⚠️ Refresh response was empty or invalid. Falling back to Phase 1 data.")
        for img in images_data:
            url = img.get("test_link") or img.get("url") if isinstance(img, dict) else img
            if url:
                if str(url).startswith("southeast"):
                    url = "https://" + str(url)
                valid_urls.append(url)

    if valid_urls:
         print(f"✅ Found {len(valid_urls)} valid URLs to analyze.")

    else:
         print("❌ No valid URLs found even after refresh.")
         return

    print(f"\n🎨 Phase 4: Analyzing Colors with Gemini")
    color_result = analyze_overall_colors(valid_urls)
    
    if not color_result:
        print("❌ Color analysis failed.")
        return
        
    print(f"🎯 Final Color Output:")
    print(f"Room Color: {color_result.room_color}")
    print(f"Element Color: {color_result.element_color}")
    print(f"Element Furniture: {color_result.element_furniture}")
    
    print(f"\n🚀 Phase 4: Submitting Color Output to API")
    
    import datetime
    import json
    
    # ตรวจสอบและบังคับให้มี 14 รายการเสมอ (เติม 0 หรือ [] ถ้าขาด)
    def ensure_14(data, default_val):
        lst = list(data)
        if len(lst) < 14:
            lst.extend([default_val] * (14 - len(lst)))
        return lst[:14]

    room_color = ensure_14(color_result.room_color, 0)
    furniture_color = ensure_14(color_result.element_color, 0)
    furniture_elements = ensure_14(color_result.element_furniture, [])

    # เรียงลำดับ Key ให้เหมือนตัวอย่าง Postman เป๊ะๆ
    payload = {
        "property_id": int(property_id),
        "analyzed_at": "2026-03-19T00:00:00.000000Z", # ใช้ตามตัวอย่างที่ Postman ส่งผ่าน
        "room_color": room_color,
        "furniture_color": furniture_color,
        "furniture_elements": furniture_elements
    }
    
    print(f"📡 Payload to POST (Formatted):\n{json.dumps(payload, indent=4)}")
    api.submit_color_analysis(payload)

    
    print(f"\n🧪 [TEST MODE] Skipping Firestore Update.")
    # Phase 5: Searching and Updating Firestore (DISABLED FOR TEST MODE)
    """
    docs = firestore.db.collection(firestore.collection_name).where("api_property_id", "==", property_id).limit(1).stream()
    doc_id = None
    for d in docs:
        doc_id = d.id
        
    if doc_id:
        furniture_storage = [", ".join(items) if items else "" for items in color_result.element_furniture]
        firestore.db.collection(firestore.collection_name).document(doc_id).update({
            "room_color": color_result.room_color,
            "element_color": color_result.element_color,
            "element_furniture": furniture_storage
        })
        print(f"✅ Saved results to Firestore.")
    """

    # print(f"\n🌐 Phase 5: Updating Agent API")
    # api_success = api.update_property(property_id, {"house_color": color_result})
    # if api_success:
    #     print(f"✅ Updated 'house_color' for Property {property_id} on Agent API.")
    # else:
    #     print(f"❌ Failed to update Agent API for Property {property_id}.")

def run_all_workflow(limit: int = 0, start_after_id: int = 0, max_id: int = 0):

    firestore = FirestoreService()
    print(f"📡 Fetching properties from Firestore{' starting after ID ' + str(start_after_id) if start_after_id > 0 else ''}...")
    
    # เพิ่ม order_by เพื่อให้ลำดับคงที่
    query = firestore.db.collection(firestore.collection_name).where("api_property_id", ">", 0).order_by("api_property_id")
    
    if limit > 0:
        query = query.limit(limit)
    
    docs = query.stream()
    docs_list = list(docs)
    
    # กรองรายการที่รันไปแล้วออก (ถ้ามีการระบุ start_after_id)
    if start_after_id > 0:
        filtered_list = []
        found = False
        for d in docs_list:
            pid = int(d.get("api_property_id") or 0)
            if pid >= start_after_id:
                if max_id > 0 and pid > max_id:
                    continue
                filtered_list.append(d)
        docs_list = filtered_list

    print(f"✅ Found {len(docs_list)} properties (Range: {start_after_id} to {max_id if max_id > 0 else 'End'})")

    # ประมวลผลทีละรายการ (Serial) เพื่อความชัดเจนของ Log และลำดับการทำงาน
    for i, d in enumerate(docs_list):
        pid = d.get("api_property_id")
        if not pid: continue
        
        print(f"\n{'='*50}")
        print(f"🔄 [{i+1}/{len(docs_list)}] Processing Property ID: {pid}")
        print(f"{'='*50}")
        
        try:
            run_workflow(int(pid))
        except Exception as e:
            print(f"❌ Error processing {pid}: {e}")
        
        # คั่นเวลานิดหน่อยเพื่อให้ Backend ไม่ทำงานหนักเกินไป
        if i < len(docs_list) - 1:
            time.sleep(2)

def run_range_workflow(start_id: int, end_id: int):
    """
    Directly loops through a numeric range of IDs from API (no Firestore).
    """
    total = end_id - start_id + 1
    print(f"🚀 Starting Range Workflow (Direct API): {start_id} to {end_id} ({total} properties)")
    
    for i, pid in enumerate(range(start_id, end_id + 1)):
        print(f"\n{'='*50}")
        print(f"🔄 [{i+1}/{total}] Processing Property ID: {pid}")
        print(f"{'='*50}")
        try:
            run_workflow(pid)
        except Exception as e:
            print(f"❌ Error with ID {pid}: {e}")
            
        time.sleep(2)  # ให้ความเสถียรกับ API






if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "all":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            run_all_workflow(limit)
        elif cmd == "range":
            if len(sys.argv) > 3:
                s_id = int(sys.argv[2])
                e_id = int(sys.argv[3])
                run_range_workflow(s_id, e_id)
            else:
                print("Usage: python reanalyze_colors_from_api.py range <start_id> <end_id>")
        elif cmd == "resume":
            if len(sys.argv) > 2:
                last_id = int(sys.argv[2])
                run_all_workflow(start_after_id=last_id, max_id=332)
            else:
                print("Usage: python reanalyze_colors_from_api.py resume <start_id>")
        elif sys.argv[1].isdigit():
            # python src/reanalyze_colors_from_api.py 285 --all
            start_id = int(sys.argv[1])
            if len(sys.argv) > 2 and sys.argv[2].lower() in ["--all", "all"]:
                # บังคับจบที่ 332 ตามโจทย์
                run_all_workflow(limit=0, start_after_id=start_id, max_id=332)
            else:
                property_id = int(sys.argv[1])
                run_workflow(property_id)
        else:
            print("Unknown command.")
    else:
        print("Usage:")
        print("1. Single property: python src/reanalyze_colors_from_api.py 332")
        print("2. Batch 285-332 (direct): python src/reanalyze_colors_from_api.py range 285 332")
        print("3. Batch 285-332 (from Firestore): python src/reanalyze_colors_from_api.py 285 --all")



