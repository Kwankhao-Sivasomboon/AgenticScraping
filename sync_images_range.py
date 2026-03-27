import os
import sys
import time
import random
import datetime
from io import BytesIO

# Setup paths
project_root = os.path.abspath(os.curdir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService
from src.room_analyzer.style_classifier import analyze_room_images, download_image

def run_image_sync_range():
    # --- CONFIG ---
    # รับค่าจาก Command Line (ถ้ามี) เช่น: python sync_images_range.py 1821 1821
    if len(sys.argv) > 1:
        start_id = int(sys.argv[1])
        end_id = int(sys.argv[2]) if len(sys.argv) > 2 else start_id
    else:
        # ค่า Default ตามที่แจ้ง
        start_id = 1821
        end_id = 2524
        
    batch_upload_size = 5 # ขนาด batch ในการอัปโหลดต่อครั้ง
    
    print("==========================================")
    print(f"🚀 เริ่มต้นการ Sync รูปภาพ (กรอง AI) ")
    print(f"📍 ช่วง ID: {start_id} - {end_id}")
    print("⚠️ เงื่อนไข: กรองรูปภาพด้วย AI (ในบ้าน/นอกบ้าน) และงดการลบลายน้ำ")
    print("==========================================")
    
    api = APIService()
    if not api.authenticate():
        print("❌ Login Agent API ล้มเหลว!")
        return
        
    fs = FirestoreService()
    
    # 🛒 ตรวจสอบว่ามีคีย์ GEMINI หรือไม่
    if not os.getenv("GEMINI_API_KEY") and not os.getenv("GEMINI_API_KEY_COLOR") and not os.getenv("GOOGLE_API_KEY"):
        print("❌ ไม่พบ API Key สำหรับ Gemini! ระบบ AI กรองรูปจะไม่ทำงาน")
        return

    # 📥 ค้นหารายการใน Firestore
    print("📦 กำลังตรวจสอบข้อมูลใน Firestore (พิกัด 1821-2524)...")
    # เนื่องจากการ Query ใน Firestore ของ Field ตัวเลขอาจมีทั้ง String และ Int บนข้อมูลเก่า
    # เราจะดึงรายการทั้งหมดใน collection มากรองในช่วง ID ที่ระบุ
    all_docs = fs.db.collection(fs.collection_name).stream()
    
    target_items = []
    for doc in all_docs:
        data = doc.to_dict()
        pid = data.get("api_property_id")
        
        # ตรวจสอบว่าอยู่ในช่วงที่กำหนด และยังไม่ได้ Sync รูป (ใช้ flag: images_synced_v2)
        if pid:
            try:
                pid_int = int(pid)
                if start_id <= pid_int <= end_id:
                    if not data.get("images_synced_v2"):
                        target_items.append({"listing_id": doc.id, "api_id": pid_int, "data": data})
            except (ValueError, TypeError):
                continue

    if not target_items:
        print("✅ ไม่พบรายการที่รอการ Sync รูปภาพเพิ่มในช่วงนี้ (หรืออาจ Sync ไปหมดแล้ว)")
        return
        
    # Sort by api_id so we process them in numerical order (e.g. 1823, 1824) instead of randomly
    target_items.sort(key=lambda x: x["api_id"])
    
    print(f"🔥 พบทั้งหมด {len(target_items)} รายการที่จะดำเนินการ...")

    for idx, item in enumerate(target_items, 1):
        listing_id = item["listing_id"]
        api_id = item["api_id"]
        data = item["data"]
        image_urls = data.get("images", [])
        
        print(f"\n[{idx}/{len(target_items)}] 🔄 Listing: {listing_id} -> API ID: {api_id}")
        
        if not image_urls:
            print("   ⏭️ ไม่มีรูปภาพใน Firestore ข้าม...")
            # ทำเครื่องหมายว่าข้ามถาวร
            fs.db.collection(fs.collection_name).document(listing_id).update({"images_synced_v2": "skipped_no_urls"})
            continue
            
        # 1. 🤖 [AI Vision Filtering] 
        print(f"   🤖 [AI] กำลังคัดกรองรูปภาพ {len(image_urls)} รูป (ภายใน/ภายนอก)...")
        # analyze_room_images จะทำการ download -> thumbnail -> call gemini 
        try:
            analysis = analyze_room_images(image_urls)
            
            if analysis:
                # 1. เลือกภาพหลัก (Interior / Main Exterior)
                valid_urls = [image_urls[i] for i in analysis.valid_image_indices if i < len(image_urls)]
                
                # --- [Fallback เฉพาะภาพที่ยอมรับได้ (Secondary)] ---
                # หาก AI กรองภาพหลักจนเหลือน้อยกว่า 3 รูป ให้หยิบภาพ "รอง" (ส่วนกลาง, สระว่ายน้ำ, ล็อบบี้) มาโปะ
                # วิธีนี้จะทำให้เราไม่เอา "ภาพขยะ" (แผนที่/ผังพื้น) มาอัปโหลดมั่วซั่วครับ
                if len(valid_urls) < 3 and analysis.secondary_image_indices:
                    print(f"   ⚠️ ภาพหลักมีน้อยกว่า 3 ({len(valid_urls)}) → กำลังดึงภาพส่วนกลาง/สิ่งอำนวยความสะดวกมาเพิ่ม...")
                    secondary_urls = [image_urls[i] for i in analysis.secondary_image_indices if i < len(image_urls)]
                    for u in secondary_urls:
                        if len(valid_urls) >= 3:
                            break
                        if u not in valid_urls:
                            valid_urls.append(u)
                        
                print(f"   ✅ สรุปเตรียมอัปโหลด {len(valid_urls)} รูป (สไตล์: {analysis.interior_style})")
            else:
                print("   ⚠️ AI ไม่พบรูปภาพที่เหมาะสมเลย -> ข้าม")
                fs.db.collection(fs.collection_name).document(listing_id).update({"images_synced_v2": "skipped_ai_zero"})
                continue
        except Exception as e:
            print(f"   ❌ AI Analysis Error: {e} -> ข้ามรายการนี้ไปก่อน")
            continue

        if not valid_urls:
            continue

        # 2. 📥 [Download and Prepare]
        print("   📥 กำลังเตรียมข้อมูลรูปภาพลง RAM (งดลบลายน้ำ)...")
        memory_files = []
        for i, url in enumerate(valid_urls):
            # ใช้ฟังก์ชัน download_image ดั้งเดิม (มี Retry ภายใน)
            img = download_image(url)
            if img:
                bio = BytesIO()
                img.save(bio, format="JPEG", quality=90)
                bio.seek(0)
                # ตั้งชื่อตาม index
                filename = f"room_{i+1}_{int(time.time())}.jpg"
                memory_files.append((filename, bio))
            else:
                print(f"      [X] ข้ามรูป {i+1} เพราะดาวน์โหลดไม่ได้")
            # หน่วงเวลาสั้นๆ ต่อรูป
            time.sleep(0.3)
            
        if not memory_files:
            print("   ❌ ไม่สามารถดึงรูปภาพที่ใช้งานได้เลย")
            continue

        # 3. 🚀 [Update to API]
        print(f"   🚀 กำลังอัปโหลด {len(memory_files)} รูปเข้า API (Batch=5)...")
        # กลับมาใช้ batch_size=5 ได้ปกติแล้ว เพราะแก้บัค Content-Type ผ่าน Postman logic แล้ว
        upload_success = api.upload_photos(api_id, memory_files, batch_size=5)
        
        if upload_success:
            print(f"   ✅ อัปโหลดรูปภาพเสร็จสิ้น!")
            # บันทึกสถานะว่าสำเร็จแล้ว
            # เตรียมข้อมูล furniture ให้เป็น list ของ string (comma separated) ตาม logic 13 matrix
            furniture_storage = [", ".join(items) if items else "" for items in getattr(analysis, 'element_furniture', [])]
            
            fs.db.collection(fs.collection_name).document(listing_id).update({
                "images_synced_v2": True,
                "interior_style": getattr(analysis, 'interior_style', '-'),
                "color": getattr(analysis, 'color', '-'),
                "room_color": getattr(analysis, 'room_color', []),
                "element_color": getattr(analysis, 'element_color', []),
                "element_furniture": furniture_storage,
                "last_color_analysis_at": datetime.datetime.now()
            })
            print(f"   📝 บันทึกสไตล์ ({getattr(analysis, 'interior_style', '-')}) และ Matrix สีลง Firestore เรียบร้อยแล้ว!")
        else:
            print(f"   ❌ อัปโหลดรูปล้มเหลว (ข้ามไปก่อน)")

        # 4. พักเล็กน้อย ไม่ต้องนานเท่าตอนที่บัค
        print(f"   💤 พัก 0.5 วินาที...")
        time.sleep(0.5)

    print("\n" + "="*40)
    print(f"🏁 เสร็จสิ้นการ Sync รูปภาพ {len(target_items)} รายการ")
    print("="*40)

if __name__ == "__main__":
    run_image_sync_range()
