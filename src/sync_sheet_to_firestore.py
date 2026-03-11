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
        rows = worksheet.get_all_records()
        print(f"      Total rows found in sheet: {len(rows)}")

        # 2. เชื่อมต่อ Firestore
        print("[2/3] Connecting to Firestore...")
        f_cred = sa_creds.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(project=f_cred.project_id, credentials=f_cred, database='livinginsider-scraping')
        collection_ref = db.collection('Leads')

        # 3. วนลูปเช็คข้อมูลและอัปเดต
        print("[3/3] Syncing Zone & Price values to Firestore...")
        updated_count = 0
        skipped_count = 0
        
        # Regex สำหรับดึง Listing ID จาก URL (เผื่อใน Sheet ไม่มี ID)
        id_pattern = re.compile(r'post-(\d+)')

        for record in rows:
            # ดึงข้อมูลสำคัญจากชื่อหัวตารางใน Sheet
            url = str(record.get('ลิงค์', record.get('URL', ''))).strip()
            # สมมติ Column Zone คือ AA หรือถ้าไม่มีหัวตาราง ให้ใช้ชื่อที่เราตั้งไว้
            zone_val = str(record.get('Zone', '')).strip()
            
            if not url or url == "-":
                continue
                
            # พยายามหา Listing ID
            listing_id = str(record.get('Listing ID', ''))
            if not listing_id or listing_id == "-":
                match = id_pattern.search(url)
                if match:
                    listing_id = match.group(1)
            
            if not listing_id:
                continue

            # ถ้ามีค่า Zone ให้เอาไปอัปเดตใน Firestore
            if zone_val and zone_val != "-":
                doc_ref = collection_ref.document(str(listing_id))
                # เช็คก่อนว่ามี Document นี้ไหม
                if doc_ref.get().exists:
                    doc_ref.set({"zone": zone_val}, merge=True)
                    updated_count += 1
                else:
                    skipped_count += 1

        print(f"\n[Done] Update complete!")
        print(f" - Updated in Firestore: {updated_count} documents")
        print(f" - Documents not found in Firestore: {skipped_count} (Maybe deleted or different ID)")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sync_sheet_zones_to_firestore()
