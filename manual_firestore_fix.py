import json
import os
from google.oauth2 import service_account
from google.cloud import firestore

# ตั้งค่ากุญแจ
SERVICE_ACCOUNT_FILE = "agentic-scraping-pptd-f7bc092f86f3.json"

def manual_firestore_fix_final():
    print(f"🚀 [FIRESTORE RE-FIX] Standardizing document 207...")
    
    try:
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
        db = firestore.Client(
            credentials=credentials, 
            project="agentic-scraping-pptd",
            database="livinginsider-scraping"
        )
        
        # ปรับข้อมูลให้ "เหมือนอันอื่น" (ลบก้อน developer map ออก เหลือแค่ developer_id)
        # และสลับภาษาให้ถูกต้องครับ
        original_data = {
            "id": 207,
            "project_id": 201,
            "developer_id": 2, # แสนสิริ
            "name_en": "Quattro Thonglor",
            "name_th": "ควอทโทร ทองหล่อ", # <-- สลับเป็นไทยให้แล้วครับ
            "built_date": "2554-01-01",
            "total_units": "427",
            "total_floors": "2836",
            "parking": "223",
            "launch_price": "9",
            "project_area_square_wa": None,
            "type": "condo",
            "lead_count": 1,
            "synced_at": "2026-04-21T10:41:31.783494",
            "specifications": {
                "parking": "223",
                "total_units": "427",
                "launch_price": "9",
                "total_floors": "2836"
            }
            # ลบ developer map ออกเพื่อให้เหมือนโครงการอื่นๆ ครับ
        }

    # ใช้ .set() แบบระบุข้อมูลใหม่ทั้งหมด เพื่อลบฟิลด์ developer เดิมออกไปครับ
        db.collection("project_condo").document("207").set(original_data)
        print(f"✅ Firestore: 'project_condo/207' is now Standard & Thai/Eng swapped.")
        
    except Exception as e:
        print(f"❌ Fix Failed: {e}")

if __name__ == "__main__":
    manual_firestore_fix_final()
