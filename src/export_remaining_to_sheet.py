import os
import sys
import gspread
from google.oauth2.service_account import Credentials
from google.cloud import firestore
from google.oauth2 import service_account as sa_creds
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def export_missing_to_sheet():
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    sheet_url = os.getenv('GOOGLE_SHEET_URL')
    
    if not sheet_url:
        print("[!] No GOOGLE_SHEET_URL found in .env")
        return

    try:
        # 1. เชื่อมต่อ Google Sheets
        print("[1/3] Connecting to Google Sheets...")
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet('LivingInsider')
        
        # ดึง URL ทั้งหมดใน Sheet มาก่อนเพื่อเช็คซ้ำ (URL อยู่คอลัมน์ U = index 20)
        existing_rows = worksheet.get_all_values()
        existing_urls = set()
        if len(existing_rows) > 1:
            for row in existing_rows[1:]:
                if len(row) > 20:
                    url = row[20].strip()
                    if url: existing_urls.add(url)
        
        print(f"      Found {len(existing_urls)} existing entries in sheet.")

        # 2. เชื่อมต่อ Firestore
        print("[2/3] Connecting to Firestore...")
        f_cred = sa_creds.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(project=f_cred.project_id, credentials=f_cred, database='livinginsider-scraping')
        
        # ดึงข้อมูลทั้งหมดจาก Leads
        docs = db.collection('Leads').stream()

        # 3. ประมวลผลและเตรียมข้อมูลลง Sheet
        print("[3/3] Analyzing Firestore data and appending to Sheet...")
        append_buffer = []
        
        for doc in docs:
            data = doc.to_dict()
            listing_id = doc.id
            url = data.get('url', '').strip()
            zone = data.get('zone', '').strip()
            
            # เงื่อนไข: 
            # 1. ต้องไม่ใช่โซนอุดมสุข 
            # 2. ต้องยังไม่มีใน Sheet
            # 3. ข้ามรายการที่มีแค่ link (legacy_import)
            if zone == "อุดมสุข":
                continue
            
            if data.get('status') == 'legacy_import':
                continue
            
            if url in existing_urls:
                continue

            # ดึงข้อมูล Analysis (Sub-collection)
            analysis_doc = doc.reference.collection('Analysis_Results').document('evaluation').get()
            eval_data = analysis_doc.to_dict() if analysis_doc.exists else {}

            # เตรียม Row ตามมาตรฐาน 26 คอลัมน์ + Zone (คอลัมน์ที่ 27)
            # โครงสร้างอ้างอิงจาก main.py
            images = data.get("images", [])
            first_image = images[0] if images else "-"
            
            row = [
                datetime.now().strftime("%Y-%m-%d"), # 1. วันที่ลง
                "-", # 2. วันที่โทร
                "-", # 3. สถานะการโทร
                "-", # 4. ขอสแกน
                "-", # 5. เข้าดูห้อง
                "-", # 6. วันที่เข้าดู
                "-", # 7. สแกน
                eval_data.get("direction", "-"), # 8. รู้ทิศ
                "-", # 9. ลงข้อมูล
                "-", # 10. วันนัดสแกน
                eval_data.get("project_name", "-"), # 11. ชื่อโครงการ
                eval_data.get("house_number", "-"), # 12. เลขที่ห้อง
                eval_data.get("floor", "-"),        # 13. ชั้น
                eval_data.get("bed_bath", "-"),     # 14. Unit Type
                eval_data.get("type", "-"),         # 15. S or R
                eval_data.get("price_sell", "-"),   # 16. ราคาขาย
                eval_data.get("price_rent", "-"),   # 17. ราคาเช่า
                eval_data.get("building_size") or eval_data.get("land_size") or eval_data.get("size", "-"), # 18. Area
                eval_data.get("phone_number", "-"), # 19. เบอร์โทรเจ้าของ

                eval_data.get("customer_name", "-"), # 20. ชื่อเจ้าของ 
                url,                                 # 21. ลิงค์ (Column U)
                "-", # 22. Remark
                "-", # 23. Feedback
                first_image, # 24. ภาพห้อง
                "-", # 25. โหลดรูป
                eval_data.get("selected_type", "condo"), # 26. ประเภททรัพย์
                zone if zone else "-"                # 27. Zone (Column AA)
            ]
            
            append_buffer.append(row)
            if len(append_buffer) >= 10: # ทยอยลงทีละ 10 เพื่อความเร็วและไม่ติด Limit
                worksheet.append_rows(append_buffer, value_input_option='USER_ENTERED')
                print(f"      Inserted {len(append_buffer)} new rows...")
                append_buffer = []

        # ลงข้อมูลที่เหลือใน Buffer
        if append_buffer:
            worksheet.append_rows(append_buffer, value_input_option='USER_ENTERED')
            print(f"      Inserted final {len(append_buffer)} rows.")

        print(f"\n✅ เสร็จสิ้น! ย้ายข้อมูลส่วนที่เหลือลง Google Sheet เรียบร้อยครับ")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    export_missing_to_sheet()
