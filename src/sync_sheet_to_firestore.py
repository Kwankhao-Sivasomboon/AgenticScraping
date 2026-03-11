import os
import sys
import gspread
import re
from google.oauth2.service_account import Credentials
from google.cloud import firestore
from google.oauth2 import service_account as sa_creds
from dotenv import load_dotenv

load_dotenv()

def sync_sheet_zones_to_firestore():
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
        
        rows = worksheet.get_all_values()
        if not rows:
            print("[!] No data in sheet.")
            return
            
        header = rows[0]
        print(f"      Total rows found in sheet: {len(rows)}")

        # หา Index ของคอลัมน์ที่ต้องการ
        url_idx = -1
        zone_idx = -1
        
        for idx, col in enumerate(header):
            col_name = col.strip().lower()
            if col_name in ['ลิงค์', 'url', 'link']:
                url_idx = idx
            if col_name in ['zone', 'โซน']:
                zone_idx = idx
        
        # Fallback ถ้าหาตามชื่อไม่เจอ ให้ใช้ index ตายตัว (U=20, AA=26)
        if url_idx == -1: url_idx = 20
        if zone_idx == -1: zone_idx = 26
        
        print(f"      Targeting Columns -> Link: Index {url_idx} ('{header[url_idx]}'), Zone: Index {zone_idx} ('{header[zone_idx]}')")

        # 2. เชื่อมต่อ Firestore
        print("[2/3] Connecting to Firestore...")
        f_cred = sa_creds.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(project=f_cred.project_id, credentials=f_cred, database='livinginsider-scraping')
        collection_ref = db.collection('Leads')

        # 3. วนลูปเช็คข้อมูลและอัปเดต
        print("[3/3] Syncing values to Firestore...")
        updated_count = 0
        skipped_count = 0
        no_id_count = 0
        no_zone_count = 0
        
        # Regex ที่ครอบคลุมทุกลิงก์ของ LivingInsider
        id_patterns = [
            re.compile(r'post-(\d+)'),
            re.compile(r'livingdetail/(\d+)'),
            re.compile(r'istockdetail/([^/.]+)\.html'), # สำหรับรูปแบบ gDgDjg_...
            re.compile(r'livingdetail/([^/.]+)\.html'), 
            re.compile(r'/([^/.]+)\.html$')               # วิธีสุดท้าย: เอาส่วนท้ายก่อน .html
        ]

        for i in range(1, len(rows)):
            row = rows[i]
            if len(row) <= url_idx: continue
            
            url = row[url_idx].strip()
            zone_val = row[zone_idx].strip() if len(row) > zone_idx else ""
            
            if not url or url == "-" or url == "":
                continue
                
            # พยายามหา Listing ID
            listing_id = None
            for pattern in id_patterns:
                match = pattern.search(url)
                if match:
                    listing_id = match.group(1)
                    break
            
            if not listing_id:
                if i < 5: # ปริ้นตัวอย่างที่พลาดแค่ 5 อันแรกเพื่อไม่ให้รก
                    print(f"      [Debug] Could not extract ID from URL at row {i+1}: {url}")
                no_id_count += 1
                continue

            if not zone_val or zone_val == "-":
                no_zone_count += 1
                continue

            # อัปเดตใน Firestore
            doc_ref = collection_ref.document(str(listing_id))
            # เช็คก่อนว่ามี Document นี้ไหม (เพื่อความชัวร์และไม่สร้างขยะ)
            doc_snap = doc_ref.get(['api_synced']) # ดึงแค่ฟิลด์เดียวเพื่อประหยัด
            
            if doc_snap.exists:
                doc_ref.update({"zone": zone_val})
                updated_count += 1
            else:
                # ถ้าไม่เจอด้วย ID ตรงๆ ลองเช็คเผื่อ ID มีเคสตัวเล็กตัวใหญ่ผสม
                skipped_count += 1

        print(f"\n✨ Sync Summary:")
        print(f" ✅ Updated in Firestore: {updated_count} documents")
        print(f" ❌ ID not found in Firestore: {skipped_count}")
        print(f" ⚠️ Rows skipped (No ID in URL): {no_id_count}")
        print(f" ⏳ Rows skipped (No Zone value): {no_zone_count}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    sync_sheet_zones_to_firestore()
