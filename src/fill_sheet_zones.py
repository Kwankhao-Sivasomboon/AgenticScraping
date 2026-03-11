import os
import sys
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

def fill_zones_in_sheet(target_zone_name="อุดมสุข"):
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    sheet_url = os.getenv('GOOGLE_SHEET_URL')
    
    if not sheet_url:
        print("[!] No GOOGLE_SHEET_URL found in .env")
        return

    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet('LivingInsider')
        
        print(f"[Sheets] Processing worksheet: {worksheet.title}...")
        
        # ดึงข้อมูลทั้งหมด
        rows = worksheet.get_all_values()
        if not rows:
            print("[!] No data found in sheet")
            return
            
        header = rows[0]
        # ตรวจสอบว่ามีคอลัมน์ 'Zone' หรือยัง (เราจะสร้างที่คอลัมน์ 27)
        target_col_index = 27 # Column AA
        
        if len(header) < target_col_index:
            print(f"[*] Adding 'Zone' header to column {target_col_index}...")
            worksheet.update_cell(1, target_col_index, "Zone")
        
        # วนลูปตั้งแต่แถวที่ 2
        updated_count = 0
        
        for i, row in enumerate(rows[1:], start=2):
            # ตรวจสอบ URL ที่ช่อง 21 (Index 20)
            url = row[20] if len(row) >= 21 else ""
            current_zone = row[26] if len(row) >= 27 else ""
            
            # ถ้ายังไม่มีข้อมูล Zone ให้เติม
            if not current_zone or current_zone == "-" or current_zone == "":
                # ในที่นี้ เราจะเติมค่า target_zone_name ลงไปดื้อๆ ตามที่คุณขอมา (สำหรับลิสต์อุดมสุข)
                worksheet.update_cell(i, target_col_index, target_zone_name)
                updated_count += 1
                if updated_count % 10 == 0:
                    print(f"Progress: {updated_count} rows updated...")

        print(f"[Done] Updated {updated_count} rows with zone: '{target_zone_name}'")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # คุณสามารถเปลี่ยนชื่อโซนตรงนี้ได้ครับ
    fill_zones_in_sheet("อุดมสุข")
