import os
import sys
import uuid
import hashlib
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from datetime import datetime


project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from google.cloud import firestore as google_firestore
from src.services.firestore_service import FirestoreService

load_dotenv()

# ==========================================
# 🛑 ตั้งค่าสำหรับการดึงข้อมูล (เปลี่ยนได้ที่นี่)
# ==========================================
NEW_SHEET_URL = "https://docs.google.com/spreadsheets/d/1fSNXzAI8zqKxJppC5K7RuZDXpQdb0DeG96G8r6fjKmk/edit?gid=0#gid=0"
SHEET_TAB_NAME = "Assets @ Accross BKK"
UPLOAD_ZONE = "คลองเตย"
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
        import traceback
        print(f"❌ จัดการ Google Sheets ล้มเหลว:")
        traceback.print_exc()
        return

    # ดึงข้อมูลทั้งหมดจาก Sheet
    print(f"📥 กำลังดึงข้อมูลจาก {tab_name}...")
    raw_values = worksheet.get_all_values()
    if not raw_values or len(raw_values) < 2:
        print("⚠️ แท็บนี้ไม่มีข้อมูล หรืออ่าน header ไม่เจอ")
        return
        
    headers = raw_values[0]
    records = []
    for row_vals in raw_values[1:]:
        record = {}
        for idx, h in enumerate(headers):
            h_clean = h.strip()
            if h_clean: # เก็บเฉพาะคอลัมน์ที่มีชื่อหัวตาราง
                record[h_clean] = row_vals[idx] if idx < len(row_vals) else ""
        records.append(record)
        
    print(f"📝 พบข้อมูลทั้งหมด {len(records)} แถวใน Google Sheet")
    
    firestore = FirestoreService()
    if not firestore.db:
        print("❌ เชื่อมตัวกับ Firestore ไม่สำเร็จ")
        return
        
    # --- TEST MODE LOGIC ---
    test_choice = input("💬 ต้องการทดสอบกี่รายการ? (ใส่ตัวเลข หรือพิมพ์ 'all' เพื่อรันทั้งหมด): ").strip().lower()
    limit = None
    if test_choice.isdigit():
        limit = int(test_choice)
        print(f"🛠️ โหมดทดสอบ: จะประมวลผลเพียง {limit} รายการแรก")
    else:
        print("🚀 โหมดปกติ: จะประมวลผลทั้งหมด")
        
    zone_input = input(f"💬 กรุณาใส่ Zone ที่ต้องการกำหนดให้ข้อมูลพวกนี้ (เช่น 'อ่อนนุช', ค่าเริ่มต้น '{UPLOAD_ZONE}'): ").strip() or UPLOAD_ZONE

    success_count = 0
    duplicate_count = 0
    skipped_count = 0
    fail_count = 0
    processed_count = 0  # นับเฉพาะรายการที่ผ่าน Zone filter และประมวลผลจริง

    for i, row in enumerate(records, start=2): # +2 เพราะ header คือ 1 และ index เริ่มจาก 0
        # เช็ค Limit (ใช้ processed_count เพื่อให้นับได้ถูกต้องทั้ง new และ update)
        if limit is not None and processed_count >= limit:
            print(f"\n✋ ครบกำหนด {limit} รายการตามที่แจ้งไว้ในโหมดทดสอบแล้ว หยุดการทำงาน...")
            break
            
        # --- ZONE FILTER: ตรวจสอบจาก Column 'โซน' (คอลัมน์ AD) ---
        row_zone = str(row.get('โซน', '')).strip()
        
        # [New] ถ้าใส่ 'all' ให้ข้ามการกรอง และใช้โซนจากในแถวนั้นๆ แทน
        if zone_input.lower() != 'all' and row_zone != zone_input:
            print(f"⏭️ ข้ามแถวที่ {i}: โซน '{row_zone}' ไม่ตรงกับตัวเลือก '{zone_input}'")
            continue
            
        # เลือกโซนที่จะบันทึก: ถ้าโหมด all ให้ใช้จาก sheet, ถ้าโหมดเจาะจงให้ใช้ตาม input
        target_zone = row_zone if zone_input.lower() == 'all' else zone_input

        # 3. จัดการ ID และเช็ค Duplicate
        link = str(row.get('ลิงค์', row.get('Link', row.get('URL', '')))).strip()
        p_name = str(row.get('ชื่อโครงการ', '-')).strip()
        h_num = str(row.get('เลขที่ห้อง', '-')).strip()
        f_num = str(row.get('ชั้น', '-')).strip()

        is_update = False
        new_listing_id = None
        
        if link and link != "-":
            # 🔗 กรณีมีลิงก์: ใช้ ID จากลิงก์ หรือ URL ตรงๆ
            extracted_id = None
            if "istockdetail/" in link:
                try: extracted_id = link.split("istockdetail/")[1].split(".html")[0]
                except: pass
            new_listing_id = extracted_id if extracted_id else f"ImportSheet_{uuid.uuid4().hex[:8]}"
            
            # เช็คซ้ำจาก URL
            existing_docs = firestore.db.collection(firestore.collection_name).where(filter=google_firestore.FieldFilter("url", "==", link)).limit(1).get()
            if len(existing_docs) > 0:
                new_listing_id = existing_docs[0].id
                is_update = True
        else:
            # 🚫 กรณีไม่มีลิงก์: สร้าง ID จาก (ชื่อโครงการ + เลขห้อง + ชั้น) เพื่อให้รันซ้ำแล้วไม่เบิ้ล
            # ใช้ SHA256 เพื่อความสั้นและเป็นระเบียบ
            unique_str = f"{p_name}_{h_num}_{f_num}"
            if unique_str == "-_-_-" : # ถ้าข้อมูลหลักไม่มีเลยจริงๆ ค่อยสุ่ม ID
                new_listing_id = f"ImportNoData_{uuid.uuid4().hex[:8]}"
            else:
                stable_hash = hashlib.sha256(unique_str.encode()).hexdigest()[:12]
                new_listing_id = f"NoLink_{stable_hash}"
            
            # เช็คซ้ำจาก ID ของเอกสารโดยตรง
            doc_check = firestore.db.collection(firestore.collection_name).document(new_listing_id).get()
            if doc_check.exists:
                is_update = True
        
        if is_update:
            print(f"⚠️ รายการนี้มีอยู่ใน Firestore แล้ว จะทำการอัปเดตข้อมูลเพิ่มให้... (ID: {new_listing_id})")
        else:
            print(f"🆕 รายการใหม่: กำลังจัดเตรียมข้อมูล... (ID: {new_listing_id})")


        # สร้างข้อมูลอัปเดต (ดึงแบบไดนามิกตามคอลัมน์ที่มีใน Sheet)
        raw_data_updates = {
            "zone": target_zone,
            "status": "new_sheet", # บันทึกสถานะตามที่ขอ แทนที่จะปล่อยเป็น active ธรรมดา
            "last_imported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_sheet": f"{doc.title} ({tab_name})"
        }

        
        # วนลูปดึงข้อมูลทุกคอลัมน์ที่มีอยู่ใน Sheet แบบไม่ต้องตั้งชื่อ Fix ไว้ก่อนเลย
        for key, value in row.items():
            k_str = str(key).strip()
            v_str = str(value).strip()
            if not k_str:
                continue
                
            # เอาข้อมูลทุกช่องใส่แบบไดนามิก (ป้องกันทับ field หลักของระบบด้วยคำนำหน้า sheet_)
            raw_data_updates[f"sheet_{k_str}"] = v_str


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
            new_import_count = 1
            
            # ตรวจสอบ listing_type จากทั้ง 2 source พร้อมกัน (ราคา + S or R column)
            sor_text = str(row.get('S or R', '')).lower().strip()
            has_sell = sell_price > 0 or 'sale' in sor_text or sor_text == 's'
            has_rent = rent_price > 0 or 'rent' in sor_text or sor_text == 'r'
            
            if has_sell and has_rent:
                listing_type = "sale_or_rent"
            elif has_rent:
                listing_type = "rent"
            elif has_sell:
                listing_type = "sale"
            else:
                listing_type = "sale"  # default สุดท้าย
            
            raw_data = {
                "url": link,
                "title": f"{row.get('ชื่อโครงการ', '')} {row.get('Unit Type', '')}",
                "sell_price": sell_price,
                "rent_price": rent_price,
                "type": listing_type,
                "status": f"new_sheet_v{new_import_count}",
                "import_count": new_import_count,
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
                "description": f"ข้อมูลเพิ่มเติม: ทิศ {str(row.get('รู้ทิศ', '-')).strip()}",
                "address": "-", 
                "living_level": "normal"
            }

            saved = firestore.save_listing(new_listing_id, raw_data, ai_analysis)
            
            if saved:
                print(f"✅ เพิ่ม {new_listing_id} เข้า Firestore แล้ว")
                success_count += 1
                processed_count += 1
            else:
                print(f"❌ ไม่สามารถเซฟ {new_listing_id} ได้")
                fail_count += 1
        else:
            # --- อัปเดตรายการเดิม (Update Existing) ---
            try:
                doc_ref = firestore.db.collection(firestore.collection_name).document(new_listing_id)
                
                # ดึงข้อมูลเดิมมาดูว่า Import ไปกี่ครั้งแล้ว และสถานะการ Sync
                old_snap = doc_ref.get()
                old_data = old_snap.to_dict() if old_snap.exists else {}
                
                # 🛑 [NEW] ถ้าเคย Sync สำเร็จไปแล้ว (api_synced == True) ให้ข้ามรายการนี้ไปเลย
                if old_data.get("api_synced") is True:
                    print(f"⏭️ ข้าม {new_listing_id}: เนื่องจากมีสถานะ api_synced เป็น True แล้ว")
                    skipped_count += 1 
                    continue

                old_count = old_data.get("import_count", 0)
                if not isinstance(old_count, int): old_count = 0
                new_import_count = old_count + 1
                
                # รวมข้อมูลจาก Sheet ไปชนกับ Root Document อย่างปลอดภัย
                raw_data_updates["import_count"] = new_import_count
                raw_data_updates["status"] = f"new_sheet_v{new_import_count}"
                raw_data_updates["api_synced"] = False # บังคับ Re-sync
                raw_data_updates["is_new_sheet"] = True # บังคับให้ระบบ Sync มองเห็นเป็นงานใหม่
                
                doc_ref.set(raw_data_updates, merge=True)
                
                # เตรียมข้อมูลสำคัญอัปเดตลง AI Analysis
                analysis_update = {}
                # ... (ส่วนอื่นเหมือนเดิม)
                if str(row.get('เบอร์โทรเจ้าของ', '')).strip() and str(row.get('เบอร์โทรเจ้าของ', '')).strip() != '-':
                    analysis_update["phone_number"] = str(row.get('เบอร์โทรเจ้าของ', '')).strip()
                if str(row.get('ชื่อเจ้าของ', '')).strip() and str(row.get('ชื่อเจ้าของ', '')).strip() != '-':
                    analysis_update["customer_name"] = str(row.get('ชื่อเจ้าของ', '')).strip()
                if str(row.get('เลขที่ห้อง', '')).strip() and str(row.get('เลขที่ห้อง', '')).strip() != '-':
                    analysis_update["house_number"] = str(row.get('เลขที่ห้อง', '')).strip()
                area_val = str(row.get('Area', '')).strip()
                if area_val and area_val != '-':
                    analysis_update["building_size"] = area_val
                
                # --- อัปเดตข้อมูลเพิ่มเติมเข้า Description (เฉพาะ ทิศ) ---
                direction = str(row.get('รู้ทิศ', '-')).strip()
                analysis_update["description"] = f"ข้อมูลเพิ่มเติม: ทิศ {direction}"
                    
                if analysis_update:
                    analysis_ref = doc_ref.collection('Analysis_Results').document('evaluation')
                    analysis_ref.set(analysis_update, merge=True)
                    
                print(f"✅ อัปเดตข้อมูลเป็น V{new_import_count} ให้ {new_listing_id} แล้ว")
                duplicate_count += 1
                processed_count += 1
            except Exception as e:
                print(f"❌ เกิดข้อผิดพลาดในการอัปเดต {new_listing_id}: {e}")
                fail_count += 1

    print(f"\n🎉 สรุปผลการ Import:")
    print(f"   - นำเข้าใหม่: {success_count} รายการ")
    print(f"   - ข้าม (เคยซิงค์แล้ว): {skipped_count} รายการ")
    print(f"   - พบข้อมูลเดิมและตั้งค่าอัปเดตแล้ว: {duplicate_count} รายการ")
    print(f"   - ล้มเหลว: {fail_count} รายการ")

if __name__ == "__main__":
    run_import()
