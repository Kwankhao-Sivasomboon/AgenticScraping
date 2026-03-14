import os
import sys
import uuid
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService

load_dotenv()

# ==========================================
# 🛑 ตั้งค่าสำหรับการดึงข้อมูล (เปลี่ยนได้ที่นี่)
# ==========================================
NEW_SHEET_URL = "https://docs.google.com/spreadsheets/d/1hHMSBt89Q22v0lO3mJmHsMEDTbZAXdlsaXNPsGkrP58/edit?gid=2052102924#gid=2052102924" # <-- ใส่ลิงก์ Google Sheet ใหม่ที่นี่ (ถ้าไม่ได้ตั้งไว้ใน .env)
SHEET_TAB_NAME = "Condo @ 4-Alley" # <-- เปลี่ยนเป็นชื่อแท็บที่ต้องการ เช่น 'ข้อมูลใหม่'
UPLOAD_ZONE = "บางนา" # <-- Zone ที่ต้องการให้ยัดใส่ลงไปใน Firestore (คุณแก้ได้เรื่อยๆ ก่อนรัน)
# ==========================================


def run_import():
    print("🚀 เริ่มกระบวนการ Import ข้อมูลจาก Google Sheet ใหม่ลง Firestore...")
    
    # 1. เชื่อม Google Sheets
    print("🔑 Authenticating Google Sheets...")
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    try:
        credentials = Credentials.from_service_account_file(
            credentials_file, 
            scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        gc = gspread.authorize(credentials)
        
        # ปกติคุณสามารถใช้ Sheet URL หรือจะรับเป็น Input จาก .env ก็ได้
        # ขอสมมติว่าคุณเอา URL วางไว้ใน NEW_SHEET_URL
        sheet_url = input("💬 กรุณาใส่ลิงก์ Google Sheet ใหม่ (หากไม่ใส่จะใช้จากตัวแปรในโค้ด): ").strip() or NEW_SHEET_URL
        
        doc = gc.open_by_url(sheet_url)
        
        tab_name = input(f"💬 กรุณาใส่ชื่อ Tab (ค่าเริ่มต้น '{SHEET_TAB_NAME}'): ").strip() or SHEET_TAB_NAME
        worksheet = doc.worksheet(tab_name)
    except Exception as e:
        print(f"❌ จัดการ Google Sheets ล้มเหลว: {e}")
        return

    # ดึงข้อมูลทั้งหมดจาก Sheet
    print(f"📥 กำลังดึงข้อมูลจาก {tab_name}...")
    records = worksheet.get_all_records()
    if not records:
        print("⚠️ แท็บนี้ไม่มีข้อมูล หรืออ่าน header ไม่เจอ")
        return
        
    print(f"📝 พบข้อมูลทั้งหมด {len(records)} แถวใน Google Sheet")
    
    # 2. เชื่อม Firestore
    print("🔥 Authenticating Firestore...")
    firestore = FirestoreService()
    if not firestore.db:
        print("❌ เชื่อมตัวกับ Firestore ไม่สำเร็จ")
        return
        
    zone_input = input(f"💬 กรุณาใส่ Zone ที่ต้องการกำหนดให้ข้อมูลพวกนี้ (เช่น 'อ่อนนุช', ค่าเริ่มต้น '{UPLOAD_ZONE}'): ").strip() or UPLOAD_ZONE

    success_count = 0
    duplicate_count = 0
    fail_count = 0

    for i, row in enumerate(records, start=2): # +2 เพราะ header คือ 1 และ index เริ่มจาก 0
        link = str(row.get('ลิงค์', '')).strip()
        if not link:
            continue
            
        print(f"\n======================================")
        print(f"🔍 กำลังตรวจสอบแถวที่ {i}: {row.get('ชื่อโครงการ', 'ไม่ระบุ')}")
        
        # 3. เช็ค Duplicate (จาก Field 'url' ใน Firestore)
        new_listing_id = f"ImportSheet_{uuid.uuid4().hex[:8]}"
        is_update = False
        
        try:
            # ใช้ query Where url == link
            existing_docs = firestore.db.collection(firestore.collection_name).where("url", "==", link).limit(1).get()
            if len(existing_docs) > 0:
                new_listing_id = existing_docs[0].id
                is_update = True
                print(f"⚠️ รายการนี้มีอยู่ใน Firestore แล้ว (URL ซ้ำ) จะทำการอัปเดตข้อมูลเพิ่มให้...")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดตอนเช็ค URL: {e}")
            fail_count += 1
            continue

        # สร้างข้อมูลอัปเดต (จะนำไปใส่ใน Root Document ของ Firestore สำหรับให้ดูผ่าน Firebase หรือ Export)
        raw_data_updates = {
            "zone": zone_input,
            "sheet_date_added": str(row.get('วันที่ลงข้อมูล', '')).strip(),
            "sheet_latest_contact": str(row.get('ติดต่อล่าสุด', '')).strip(),
            "sheet_contact_status": str(row.get('สถานะการโทร', '')).strip(),
            "sheet_is_available": str(row.get('อยู่ไหม', '')).strip(),
            "sheet_can_scan": str(row.get('ขอสแกน', '')).strip(),
            "sheet_want_marketing": str(row.get('ขอทำการตลาด', '')).strip(),
            "sheet_view_room": str(row.get('เข้าดูห้อง', '')).strip(),
            "sheet_scan": str(row.get('สแกน', '')).strip(),
            "sheet_know_direction": str(row.get('รู้ทิศ', '')).strip(),
            "sheet_add_data": str(row.get('ลงข้อมูล', '')).strip(),
            "sheet_scan_date": str(row.get('วันนัดสแกน', '')).strip(),
            "sheet_more_rooms": str(row.get('ห้องเพิ่มเติม', '')).strip(),
            "sheet_feedback": str(row.get('Feedback', '')).strip()
        }
        
        # จัดการ Remark หลายๆ คอลัมน์ (เผื่อมี 2 อันแบบในตัวอย่าง)
        remarks = []
        for key, value in row.items():
            if 'Remark' in str(key) and str(value).strip():
                remarks.append(str(value).strip())
        raw_data_updates["sheet_remark"] = " | ".join(remarks)


        # แปลงข้อมูลราคา (ลบเครื่องหมาย ฿, คอมมา, และช่องว่างทิ้ง)
        sell_price_text = str(row.get('ราคาขาย', '0')).replace(',', '').replace('฿', '').strip()
        rent_price_text = str(row.get('ราคาเช่า', '0')).replace(',', '').replace('฿', '').strip()
        
        try: sell_price = float(sell_price_text) if sell_price_text and sell_price_text != '-' else 0
        except: sell_price = 0
        
        try: rent_price = float(rent_price_text) if rent_price_text and rent_price_text != '-' else 0
        except: rent_price = 0

        # จัดการ Unit Type
        unit_type = str(row.get('Unit Type', ''))
        bedrooms = 0
        bathrooms = 0
        if 'bed' in unit_type.lower() or 'ห้องนอน' in unit_type.lower():
            try: bedrooms = int(''.join(filter(str.isdigit, unit_type)) or 1)
            except: pass

        if not is_update:
            # --- สร้างรายการใหม่ (New Listing) ---
            raw_data = {
                "url": link,
                "title": f"{row.get('ชื่อโครงการ', '')} {row.get('Unit Type', '')}",
                "sell_price": sell_price,
                "rent_price": rent_price,
                "type": "sale" if 's' in str(row.get('S or R', '')).lower() else ("rent" if 'r' in str(row.get('S or R', '')).lower() else "sale"),
                "status": "active",
                "api_synced": False # ตั้งเป็น False เพื่อให้ระบบหลักดึงไปอัปโหลดเข้า Agent API !
            }
            raw_data.update(raw_data_updates) # รวมฟิลด์พิเศษจากชีตเข้าไปด้วย

            ai_analysis = {
                "project_name": str(row.get('ชื่อโครงการ', '-')).strip(),
                "house_number": str(row.get('เลขที่ห้อง', '-')).strip(),
                "floor": str(row.get('ชั้น', '-')).strip(),
                "bedrooms": str(bedrooms),  
                "bathrooms": str(bathrooms),
                "building_size": str(row.get('Area', '0')).strip(),
                "land_size": "0", 
                "phone_number": str(row.get('เบอร์โทรเจ้าของ', '-')).strip(),
                "customer_name": str(row.get('ชื่อเจ้าของ', '-')).strip(),
                "type": "condo", 
                "specifications": {
                    "floors": str(row.get('ชั้น', '-')).strip()
                },
                "description": f"ข้อมูลเพิ่มเติม: ทิศ {str(row.get('รู้ทิศ', '-')).strip()} | {raw_data_updates['sheet_remark']}",
                "address": "-", 
                "living_level": "normal"
            }

            saved = firestore.save_listing(new_listing_id, raw_data, ai_analysis)
            
            if saved:
                print(f"✅ เพิ่ม {new_listing_id} เข้า Firestore แล้ว")
                success_count += 1
            else:
                print(f"❌ ไม่สามารถเซฟ {new_listing_id} ได้")
                fail_count += 1
        else:
            # --- อัปเดตรายการเดิม (Update Existing) ---
            try:
                doc_ref = firestore.db.collection(firestore.collection_name).document(new_listing_id)
                # รวมข้อมูลจาก Sheet ไปชนกับ Root Document อย่างปลอดภัย
                doc_ref.set(raw_data_updates, merge=True)
                
                # เตรียมข้อมูลสำคัญอัปเดตลง AI Analysis
                analysis_update = {}
                if str(row.get('เบอร์โทรเจ้าของ', '')).strip() and str(row.get('เบอร์โทรเจ้าของ', '')).strip() != '-':
                    analysis_update["phone_number"] = str(row.get('เบอร์โทรเจ้าของ', '')).strip()
                if str(row.get('ชื่อเจ้าของ', '')).strip() and str(row.get('ชื่อเจ้าของ', '')).strip() != '-':
                    analysis_update["customer_name"] = str(row.get('ชื่อเจ้าของ', '')).strip()
                if str(row.get('เลขที่ห้อง', '')).strip() and str(row.get('เลขที่ห้อง', '')).strip() != '-':
                    analysis_update["house_number"] = str(row.get('เลขที่ห้อง', '')).strip()
                area_val = str(row.get('Area', '')).strip()
                if area_val and area_val != '-':
                    analysis_update["building_size"] = area_val
                    
                if analysis_update:
                    analysis_ref = doc_ref.collection('Analysis_Results').document('evaluation')
                    analysis_ref.set(analysis_update, merge=True)
                    
                print(f"✅ อัปเดตข้อมูลเพิ่มเติมให้ {new_listing_id} แล้ว")
                duplicate_count += 1 # นับรวมในช่องซ้ำ (แต่อัปเดตแล้ว)
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดในการอัปเดต {new_listing_id}: {e}")
                fail_count += 1

    print(f"\n🎉 สรุปผลการ Import:")
    print(f"   - นำเข้าใหม่: {success_count} รายการ")
    print(f"   - พบข้อมูลเดิมและตั้งค่าอัปเดตแล้ว: {duplicate_count} รายการ")
    print(f"   - ล้มเหลว: {fail_count} รายการ")

if __name__ == "__main__":
    run_import()
