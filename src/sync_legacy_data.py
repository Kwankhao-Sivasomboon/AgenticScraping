import os
import sys
from datetime import datetime

# Add src to path if needed (though we'll run from root)
sys.path.append(os.path.join(os.getcwd(), 'src'))

from sheets_service import SheetsService
from firestore_service import FirestoreService

def sync_data():
    """
    ดึงข้อมูล URL จาก Google Sheets (คอลัมน์ U) 
    และนำไปบันทึกไว้ใน Firestore เพื่อประโยขน์ในการเช็กรายการซ้ำ (Deduplication)
    """
    print("\n🚀 [Migration] เริ่มต้นการซิงค์ข้อมูลจาก Google Sheets ลง Firestore...")
    
    try:
        sheets = SheetsService()
        firestore = FirestoreService()
        
        if not sheets.sheet:
            print("❌ ไม่สามารถเชื่อมต่อ Google Sheets ได้ ตรวจสอบเครดิตเนเชียลและ URL")
            return

        print("⏳ กำลังดึงข้อมูลทั้งหมดจาก Google Sheets (LivingInsider)...")
        # ดึงค่าทั้งหมดมาเป็น List of Lists
        all_values = sheets.sheet.get_all_values()
        
        if len(all_values) <= 1:
            print("⚠️ ไม่พบข้อมูลใน Google Sheets หรือมีแค่หัวตาราง")
            return

        # ลบหัวตารางออก
        data_rows = all_values[1:]
        print(f"📊 พบข้อมูลทั้งหมด {len(data_rows)} แถว")

        count = 0
        skipped = 0
        
        for idx, row in enumerate(data_rows):
            # คอลัมน์ U คือ Index 20 (เริ่มนับจาก 0)
            if len(row) <= 20:
                continue
                
            url = row[20].strip()
            
            # ตรวจสอบว่าเป็นลิงก์ LivingInsider หรือไม่
            if "livinginsider.com" in url:
                # สกัด Listing ID จาก URL (เช่น .../12345/abc.html -> 12345 หรือรหัสท้ายสุด)
                # ปกติ LivingInsider ใช้รหัสท้ายสุดก่อน .html
                listing_id = url.split('/')[-1].replace('.html', '')
                
                # ถ้า URL เป็นรูปแบบอื่นที่ไม่มี .html เช่น /istockdetail/gDgDjg_CobDIjC
                if '/' in listing_id:
                    listing_id = listing_id.split('/')[-1]

                # เช็คใน Firestore ว่ามีหรือยัง
                if not firestore.is_listing_exists(listing_id):
                    # สร้างข้อมูลจำลอง (Placeholder) เพื่อให้ระบบรู้ว่าเคยทำรายการนี้แล้ว
                    placeholder_data = {
                        "listing_id": listing_id,
                        "url": url,
                        "status": "legacy_import",
                        "image_zip_url": "-",
                        "sync_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                    # ข้อมูล AI ผลประโยชน์ชั่วคราว
                    placeholder_ai = {
                        "status": "imported_from_sheets",
                        "note": "Synchronized from existing Google Sheets records"
                    }
                    
                    if firestore.save_listing(listing_id, placeholder_data, placeholder_ai):
                        count += 1
                        if count % 10 == 0:
                            print(f"✅ บันทึกแล้ว {count} รายการ...")
                else:
                    skipped += 1
            else:
                skipped += 1

        print(f"\n✨ [สำเร็จ] เพิ่มข้อมูลเข้าคลังเช็คซ้ำเรียบร้อย!")
        print(f"📝 รายการใหม่ที่บันทึก: {count}")
        print(f"⏭️ รายการที่ข้าม (ซ้ำหรือลิงก์ไม่ถูกต้อง): {skipped}")
        print(f"🏁 รวมรายการทั้งหมดในระบบเช็คซ้ำขณะนี้จะเพิ่มขึ้น {count} รายการ")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดเด็ดขาด: {e}")

if __name__ == "__main__":
    sync_data()
