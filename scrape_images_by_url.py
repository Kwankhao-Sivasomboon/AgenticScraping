"""
Script: scrape_images_by_url.py
Description: อ่าน URL จาก Firestore (สถานะ new_sheet) เพื่อใช้ Playwright เข้าไปดึงรูปภาพ (images) 
และบันทึกอัปเดตกลับลงไปใน Firestore (ช่อง images_url/images) เพื่อเตรียมพร้อมสำหรับ Sync เข้า Agent API ต่อไป
"""

import time
import random
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from src.services.firestore_service import FirestoreService
from src.config import SHOW_BROWSER

def random_sleep(min_sec=2, max_sec=4):
    time.sleep(random.uniform(min_sec, max_sec))

def extract_images_from_page(page):
    """ฟังก์ชันสกัดรูปภาพ คัดลอก Logic มาจาก scraper_agent.py"""
    image_urls = []
    try:
        # เปิด LightGallery หรือ Popup ถ้ามี (บางครั้งรูปใหญ่อยู่ใน Modal)
        page.evaluate('''() => {
            let cover = document.querySelector('.owl-item.active img, .image-istock, #img-cover');
            if(cover) cover.click();
        }''')
        random_sleep(1, 2)
        
        # กวาด URL รูปภาพ
        image_urls = page.evaluate('''() => {
            let imgs = Array.from(document.querySelectorAll('.lg-thumb-item img, .lg-item img, .image-istock, img[src*="og_detail"], img[src*="upload/topic"]'));
            let urls = imgs.map(img => img.src || img.getAttribute('data-src'));
            
            let validUrls = urls.filter(src => {
                if (!src) return false;
                if (!src.includes('http')) return false;
                let lowerSrc = src.toLowerCase();
                if (['avatar', 'icon', 'banner', 'logo'].some(v => lowerSrc.includes(v))) return false;
                return src.includes('livinginsider.com') && (src.includes('og_detail') || src.includes('upload/topic'));
            });
            return [...new Set(validUrls)].slice(0, 50); // ดึงรูปภาพสูงสุด 50 รูป เพื่อไม่ให้หนักเกินไป
        }''')
        
        # ปิดแกลลอรี่กดย้อนกลับ
        page.keyboard.press('Escape')
        random_sleep(0.5, 1)
        
    except Exception as e:
        print(f"⚠️ เกิดข้อผิดพลาดในการดึงรูปภาพ: {e}")
        
    return image_urls

def run_image_scraper():
    print("🚀 เริ่มต้นกระบวนการ Scrape เฉพาะรูปภาพสำหรับทรัพย์ใหม่ (status: new_sheet)")
    
    firestore = FirestoreService()
    if not firestore.db:
        print("❌ เชื่อมต่อ Firestore ไม่สำเร็จ")
        return
        
    # 1. ค้นหาเอกสารใน Firestore
    print("📦 กำลังค้นหารายการที่ต้องการดึงรูปภาพ (status: new_sheet & images.length == 0)...")
    
    query = firestore.db.collection(firestore.collection_name).where("status", "==", "new_sheet")
    
    docs = query.stream()
    
    target_listings = []
    for doc in docs:
        doc_id = doc.id
        
        # ⚠️ ข้ามรายการที่มาจาก Facebook Group (ชื่อขึ้นต้นด้วย ImportSheet)
        if doc_id.startswith("ImportSheet"):
            continue
            
        data = doc.to_dict()
        images = data.get('images', [])
        
        # ค้นหา URL จากฟิลด์ที่มีความเป็นไปได้ต่างๆ
        url = data.get('url') or data.get('sheet_ลิงค์') or data.get('sheet_Link') or data.get('sheet_URL') or ""
        
        if not images and url:
             target_listings.append({
                 'id': doc_id,
                 'url': url
             })
             
    if not target_listings:
        print("✅ ไม่พบรายการที่ต้องไปดึงรูปภาพเพิ่มเติม")
        return
        
    print(f"🔥 พบเป้าหมายที่ต้องไปดึงรูปภาพ {len(target_listings)} รายการ")
    
    # 2. เริ่มเปิด Playwright
    with sync_playwright() as p:
        # เปิด Browser
        browser_type = p.chromium
        browser = browser_type.launch(
            headless=not SHOW_BROWSER,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        
        success_count = 0
        fail_count = 0
        
        # 3. วนลูปเข้าไปทีละ URL เพื่อดึงรูป
        for i, item in enumerate(target_listings, 1):
            doc_id = item['id']
            url = item['url']
            
            # ✨ เปิดหน้าใหม่ทุกลำดับเพื่อลดการสะสมของ RAM
            page = context.new_page()
            stealth_sync(page)
            
            print(f"\n[{i}/{len(target_listings)}] 🔄 กำลังเข้าถึง URL: {url}")
            try:
                # เข้าหน้าเว็บ
                page.goto(url, wait_until='domcontentloaded', timeout=45000)
                random_sleep(3, 5) # รอให้เว็บโหลดรูปเสร็จ
                
                # ดึงรูปภาพ
                print("📸 กำลังสกัดลิงก์รูปภาพ...")
                image_urls = extract_images_from_page(page)
                
                if image_urls:
                    print(f"✅ พบรูปภาพจำนวน {len(image_urls)} รูป")
                    
                    # อัปเดตกลับลง Firestore
                    doc_ref = firestore.db.collection(firestore.collection_name).document(doc_id)
                    doc_ref.update({
                        'images': image_urls,
                        'api_synced': False # บังคับให้เกิดการ Sync ใหม่ในกรณีที่ต้องการส่งรูปลง API ในอนาคต
                    })
                    print(f"💾 บันทึกรูปลง Firestore (ID: {doc_id}) สำเร็จ")
                    success_count += 1
                else:
                    print("⚠️ ไม่พบรูปภาพในหน้านี้ (อาจถูกลบ หรือโหลดไม่ขึ้น)")
                    # อัปเดตเป็น List ว่างไว้ ไม่ต้องค้นซ้ำแล้วซ้ำอีก
                    doc_ref = firestore.db.collection(firestore.collection_name).document(doc_id)
                    doc_ref.update({'images': []}) 
                    fail_count += 1
                    
            except Exception as e:
                print(f"❌ ดึงข้อมูลลิงก์ {url} ไม่สำเร็จ: {e}")
                fail_count += 1
            finally:
                # 🛡️ ปิดหน้าเว็บทุกครั้งเพื่อคืน RAM
                page.close()
                
            # พักหายใจก่อนเข้าหน้าถัดไป
            sleep_time = random.uniform(2, 5)
            print(f"💤 รอ {sleep_time:.1f} วินาทีก่อนไปต่อ...")
            time.sleep(sleep_time)
            
        browser.close()
        
    print(f"\n🎉 สรุปผลการ Scrape รูปภาพ -> เจอรูป: {success_count} คิว | ไม่เปิด/ไม่เจอ: {fail_count} คิว")

if __name__ == "__main__":
    run_image_scraper()
