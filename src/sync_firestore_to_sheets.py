import os
import sys
from datetime import datetime

# Ensure project root is in the python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.sheets_service import SheetsService

def main():
    print("=== เริ่มดึงข้อมูลจาก Firestore ไปลง Google Sheets ===")
    
    firestore = FirestoreService()
    sheets = SheetsService()
    
    # ดึงข้อมูลจาก collection 'Leads' (ชื่อจริงที่ใช้ใน firestore_service.py)
    docs = list(firestore.db.collection(firestore.collection_name).stream())
    
    print(f"เจอข้อมูลใน Firestore ทั้งหมด {len(docs)} รายการ")
    
    synced_count = 0
    failed_count = 0
    
    for doc in docs:
        raw_data = doc.to_dict()
        listing_id = doc.id

        # ดึงข้อมูล AI Evaluation จาก Sub-collection
        analysis_doc = doc.reference.collection('Analysis_Results').document('evaluation').get()
        ai_eval = analysis_doc.to_dict() if analysis_doc.exists else {}
        
        images = raw_data.get("images", [])
        first_image = images[0] if images else "-"
        
        # ดึง zone และ property_type ที่เก็บไว้ใน raw_data
        zone = raw_data.get("zone", "-")
        property_type = raw_data.get("property_type", "-")
        
        sheet_row = [
            datetime.now().strftime("%Y-%m-%d"), # 1. วันที่ลง
            "-",                                  # 2. วันที่โทร
            "-",                                  # 3. สถานะการโทร
            "-",                                  # 4. ขอสแกน
            "-",                                  # 5. เข้าดูห้อง
            "-",                                  # 6. วันที่เข้าดู
            "-",                                  # 7. สแกน
            ai_eval.get("direction", "ไม่ระบุทิศ"), # 8. รู้ทิศ
            "-",                                  # 9. ลงข้อมูล
            "-",                                  # 10. วันนัดสแกน
            ai_eval.get("project_name", "-"),     # 11. ชื่อโครงการ
            ai_eval.get("house_number", "-"),     # 12. เลขที่ห้อง
            ai_eval.get("floor", "-"),            # 13. ชั้น
            ai_eval.get("bed_bath", "-"),         # 14. Unit Type
            ai_eval.get("type", "-"),             # 15. S or R
            ai_eval.get("price_sell", "-"),       # 16. ราคาขาย
            ai_eval.get("price_rent", "-"),       # 17. ราคาเช่า
            ai_eval.get("size", "-"),             # 18. Area
            ai_eval.get("phone_number", "-"),     # 19. เบอร์โทรเจ้าของ
            ai_eval.get("customer_name", "-"),    # 20. ชื่อเจ้าของ
            raw_data.get("url", "-"),             # 21. ลิงค์
            "-",                                  # 22. Remark
            "-",                                  # 23. Feedback
            first_image,                          # 24. ภาพห้อง
            zone,                                 # 25. Zone (เพิ่มใหม่)
            property_type                         # 26. ประเภททรัพย์
        ]
        
        project_name = ai_eval.get('project_name', f'ID:{listing_id}')
        print(f"กำลังโยนข้อมูล: {project_name} [zone={zone}] ลง Sheet... ", end="", flush=True)
        
        if sheets.append_data(sheet_row):
            print("✅")
            synced_count += 1
        else:
            print("❌")
            failed_count += 1
            
    print(f"\n--- สำเร็จ {synced_count} รายการ | ล้มเหลว {failed_count} รายการ (จากทั้งหมด {len(docs)}) ---")

if __name__ == "__main__":
    main()
