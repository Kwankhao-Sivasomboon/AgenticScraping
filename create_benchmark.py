import os
import io
import time
import requests
from PIL import Image
from dotenv import load_dotenv

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

load_dotenv()
BASE_URL = os.getenv('AGENT_API_BASE_URL', 'https://dev.yourhome.co.th/api')

def optimize_image(image_bytes, format_ext, quality=100, max_size=None):
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("P", "RGBA"): img = img.convert("RGBA")
    elif img.mode != "RGB": img = img.convert("RGB")
    
    if max_size:
        img.thumbnail((max_size, max_size))
        
    out_io = io.BytesIO()
    
    if format_ext.upper() == "AVIF":
        try: import pillow_avif
        except ImportError: pass
        
    img.save(out_io, format=format_ext.upper(), quality=quality)
    return out_io.getvalue()

def process_benchmark():
    os.makedirs('benchmark_web/images_jpg', exist_ok=True)
    os.makedirs('benchmark_web/images_avif', exist_ok=True)
    os.makedirs('benchmark_web/images_webp', exist_ok=True)
    
    fs = FirestoreService()
    
    print("🔍 ดึงข้อมูล Property จาก Firestoreโดยตรง (ไม่ผ่าน API)...")
    docs = fs.db.collection('Leads').limit(500).stream() 
    
    image_urls = []
    
    for doc in docs:
        if len(image_urls) >= 200: break
        data = doc.to_dict()
        images = data.get("images", [])
        
        if isinstance(images, dict):
            flat_images = []
            for k, v in images.items():
                if isinstance(v, list): flat_images.extend(v)
            images = flat_images
            
        if not isinstance(images, list): continue

        for img in images:
            if isinstance(img, dict) and img.get("url"):
                image_urls.append(img.get("url"))
                if len(image_urls) >= 200: break
            elif isinstance(img, str) and img.startswith("http"):
                image_urls.append(img)
                if len(image_urls) >= 200: break
                        
    print(f"✅ พบ URL รูปภาพทั้งหมด {len(image_urls)} รูป กำลังประมวลผลเป็นขนาด Original (No 512px Resize)...")
    
    jpg_sizes, avif_sizes, webp_sizes = [], [], []
    
    for i, url in enumerate(image_urls):
        print(f"   📥 ประมวลผลรูปที่ {i+1}/{len(image_urls)}...")
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                original_bytes = r.content
                
                # 1. JPG
                jpg_bytes = optimize_image(original_bytes, "JPEG", max_size=None)
                with open(f"benchmark_web/images_jpg/img_{i}.jpg", "wb") as f: f.write(jpg_bytes)
                jpg_sizes.append(len(jpg_bytes))
                
                # 2. AVIF
                avif_bytes = optimize_image(original_bytes, "AVIF", max_size=None)
                with open(f"benchmark_web/images_avif/img_{i}.avif", "wb") as f: f.write(avif_bytes)
                avif_sizes.append(len(avif_bytes))
                
                # 3. WebP
                webp_bytes = optimize_image(original_bytes, "WEBP", max_size=None)
                with open(f"benchmark_web/images_webp/img_{i}.webp", "wb") as f: f.write(webp_bytes)
                webp_sizes.append(len(webp_bytes))
                
        except Exception as e:
            print(f"   ❌ ไม่สามารถประมวลผลรูปที่ {i+1}: {e}")
            
    print("\n--- 📊 สถิติเปรียบเทียบขนาด (Original Resolution) ---")
    if jpg_sizes:
        avg_jpg = sum(jpg_sizes)/len(jpg_sizes)/1024
        avg_avif = sum(avif_sizes)/len(avif_sizes)/1024
        avg_webp = sum(webp_sizes)/len(webp_sizes)/1024
        print(f"🔵 JPG :  เฉลี่ย {avg_jpg:.1f} KB")
        print(f"🟢 AVIF:  เฉลี่ย {avg_avif:.1f} KB (ประหยัดจาก JPG {100-(avg_avif/avg_jpg*100):.1f}%)")
        print(f"🟠 WebP:  เฉลี่ย {avg_webp:.1f} KB (ประหยัดจาก JPG {100-(avg_webp/avg_jpg*100):.1f}%)")
        print("-------------------------------------------------")
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #f8f9fa; margin: 0; padding: 20px; }}
            .header {{ background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }}
            .gallery {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }}
            .gallery img {{ width: 140px; height: 140px; object-fit: cover; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .nav {{ display: flex; gap: 10px; margin-top: 15px; }}
            .nav-button {{ padding: 8px 16px; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 14px; }}
            .btn-jpg {{ background: #007bff; }}
            .btn-webp {{ background: #fd7e14; }}
            .btn-avif {{ background: #28a745; }}
            .active {{ outline: 3px solid black; opacity: 0.8; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>{title} ({count} Photos)</h2>
            <p>เทียบความเร็วและขนาดไฟล์ (Disable Cache ใน F12 > Network)</p>
            <div class="nav">
                <a class="nav-button btn-jpg {active_jpg}" href="index_jpg.html">หน้า JPG</a>
                <a class="nav-button btn-webp {active_webp}" href="index_webp.html">หน้า WebP</a>
                <a class="nav-button btn-avif {active_avif}" href="index_avif.html">หน้า AVIF</a>
            </div>
        </div>
        <div class="gallery">
            {images}
        </div>
    </body>
    </html>
    """
    
    formats = [
        ("jpg", "images_jpg", "jpg", "📈 JPG (Original Size)"),
        ("avif", "images_avif", "avif", "🚀 AVIF (Original Size)"),
        ("webp", "images_webp", "webp", "⚡ WebP (Original Size)")
    ]
    
    for fmt_id, folder, ext, title in formats:
        imgs_html = "\n".join([f'<img src="{folder}/img_{i}.{ext}">' for i in range(len(jpg_sizes))])
        content = html_template.format(
            title=title, count=len(jpg_sizes), images=imgs_html,
            active_jpg="active" if fmt_id=="jpg" else "",
            active_webp="active" if fmt_id=="webp" else "",
            active_avif="active" if fmt_id=="avif" else ""
        )
        with open(f"benchmark_web/index_{fmt_id}.html", "w", encoding="utf-8") as f:
            f.write(content)

    print("\n✅ อัปเดตเว็บจำลองสำเร็จ! (Original Resolution) เข้าไปที่ http://localhost:8000/index_jpg.html")

if __name__ == "__main__":
    process_benchmark()
