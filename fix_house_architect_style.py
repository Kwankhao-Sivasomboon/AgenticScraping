"""
fix_house_architect_style.py
============================
Analyze house architectural style (exterior) for house properties.
Filters: sheet_ประเภททรัพย์ == 'บ้านมือ 2' or 'บ้านมือ 1' or property_type == 'บ้าน'
Output: architect_style (Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other)
Model: gemini-2.0-flash-lite (Fast and Cheap)
"""

import os
import sys
import time
import requests
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

project_root = os.path.abspath(os.curdir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService

def fast_download(url: str):
    """Download image with 3s timeout, no retry — fail fast."""
    try:
        r = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert("RGB")
            img.thumbnail((512, 512))
            return img
    except:
        pass
    return None

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

VALID_STYLES = ["Modern", "Nordic", "Contemporary", "Minimalist", "Loft", "Luxury", "Other"]

class HouseExteriorStyle(BaseModel):
    architect_style: str = Field(
        description="Exterior architectural style: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other"
    )

def analyze_exterior_style(image_urls: list[str]) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY_COLOR") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("   [!] No Gemini API Key found.")
        return None

    client = genai.Client(api_key=api_key)

    # ดาวน์โหลด 10 รูปพร้อมกัน (Parallel, 3s timeout each)
    urls_to_fetch = image_urls[:10]
    pil_images = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fast_download, url): url for url in urls_to_fetch}
        for future in as_completed(futures, timeout=15):
            try:
                img = future.result()
                if img:
                    pil_images.append(img)
            except:
                pass

    print(f"   AI: Loaded {len(pil_images)} images for analysis.")
    if not pil_images:
        print("   [!] Could not load any images.")
        return None

    prompt = (
        "Analyze these house exterior images and identify the architectural style. "
        "IMPORTANT: Most Thai housing projects (หมู่บ้านจัดสรร) should be classified as 'Contemporary' if they look like standard developers' houses (classic gable roof, standard concrete/tiled finish). "
        "Use 'Other' ONLY for non-residential structures like warehouses or commercial buildings. "
        "\nSTYLE GUIDELINE:\n"
        "- Contemporary: Standard Thai housing projects with mixed classic/modern gable roofs.\n"
        "- Modern: Boxy shapes, sleek flat roofs, large glass windows, minimal ornamentation.\n"
        "- Nordic: High-pitched triangle gable roofs, European cottage feel, high ceilings.\n"
        "- Minimalist: Simple clean lines, white/natural wood tones, very sparse decoration.\n"
        "- Loft: Exposed concrete, brick walls, industrial look, black metal frames.\n"
        "- Luxury: Grand mansions with classical columns, domes, or very expensive-looking facade decoration.\n"
        "\nChoose EXACTLY ONE from the list: Modern, Nordic, Contemporary, Minimalist, Loft, Luxury, Other."
    )

    contents = [prompt] + pil_images

    print(f"   AI: Analyzing architect_style using gemini-2.5-flash-lite...")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=HouseExteriorStyle,
                    temperature=0.1
                )
            )
            result = HouseExteriorStyle.model_validate_json(response.text)
            style = result.architect_style.strip()
            if style not in VALID_STYLES:
                style = "Other"
            return style
        except Exception as e:
            if "503" in str(e) and attempt < 2:
                time.sleep((attempt + 1) * 3)
                continue
            print(f"   AI Error: {e}")
            return None
    return None

def is_house_type(data: dict) -> bool:
    sheet_type = str(data.get("sheet_ประเภททรัพย์", "")).strip()
    if sheet_type in ("\u0e1a\u0e49\u0e32\u0e19\u0e21\u0e37\u0e2d 2", "\u0e1a\u0e49\u0e32\u0e19\u0e21\u0e37\u0e2d 1"):
        return True
    prop_type = str(data.get("property_type", "")).strip()
    if prop_type == "\u0e1a\u0e49\u0e32\u0e19":
        return True
    return False

def fix_house_architect_style(start_id: int = None, end_id: int = None):
    fs = FirestoreService()

    print("=" * 60)
    print("Fix House Architect Style (Exterior Only)")
    print(f"Range: {start_id or 'ALL'} - {end_id or 'ALL'}")
    print("=" * 60)

    print("Loading documents from Firestore...")
    all_docs = list(fs.db.collection(fs.collection_name).stream())
    print(f"Total documents loaded: {len(all_docs)}")

    targets = []
    for doc in all_docs:
        data = doc.to_dict()
        pid = data.get("api_property_id")

        if start_id or end_id:
            try:
                pid_int = int(pid)
                if start_id and pid_int < start_id: continue
                if end_id and pid_int > end_id: continue
            except: continue

        if not is_house_type(data):
            continue

        existing_style = str(data.get("architect_style", "")).strip()
        if existing_style and existing_style not in ("", "-", "None", "null", "Other"):
            continue

        images = data.get("images", [])
        if not isinstance(images, list) or not images:
            continue

        targets.append({
            "doc_id": doc.id,
            "api_id": pid,
            "sheet_type": data.get("sheet_ประเภททรัพย์", "-"),
            "prop_type": data.get("property_type", "-"),
            "images": images,
        })

    print(f"\nFound {len(targets)} house targets without architect_style\n")

    fixed = 0
    skipped = 0

    for idx, item in enumerate(targets, 1):
        doc_id = item["doc_id"]
        api_id = item["api_id"]
        images = item["images"]

        print(f"[{idx}/{len(targets)}] Doc: {doc_id} | API: {api_id}")
        print(f"   Type: {item['sheet_type']} | property_type: {item['prop_type']}")
        
        style = analyze_exterior_style(images)
        if not style:
            print("   Skip: No style returned.")
            skipped += 1
            continue

        print(f"   Result -> {style}")
        fs.db.collection(fs.collection_name).document(doc_id).update({
            "architect_style": style
        })
        fixed += 1
        time.sleep(0.3)

    print("\n" + "=" * 60)
    print(f"Finished! Updates: {fixed} | Skipped: {skipped}")
    print("=" * 60)

if __name__ == "__main__":
    start_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    end_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    fix_house_architect_style(start_id, end_id)
