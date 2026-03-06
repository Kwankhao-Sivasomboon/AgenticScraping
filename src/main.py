from datetime import datetime
from sheets_service import SheetsService
from scraper_agent import ScraperAgent
from evaluator_agent import EvaluatorAgent
from firestore_service import FirestoreService
from drive_service import DriveService

def main():
    print("=== Starting Agentic AI Scraping Workflow (Detailed Hybrid) ===")
    
    # 1. Initialize Services
    try:
        sheets = SheetsService()
        scraper = ScraperAgent()
        evaluator = EvaluatorAgent()
        firestore = FirestoreService()
        drive = DriveService()
    except Exception as e:
        print(f"Error initializing services: {e}")
        return

    # 2. Ingestion Phase: Scraper Agent 
    print("\n--- Ingestion Phase ---")
    # For testing, we are just executing the scraper setup directly with Playwright 
    target_url = "https://www.livinginsider.com/?srsltid=AfmBOooDgW_K_dldNP20QHs4sLi2OMdto01GWcucYKCxjlSbubJaGHqe"
    
    # You can now specify property type and zone using a Random Pick strategy
    from config import PROPERTY_TYPES, TARGET_ZONES, MAX_RETRIES
    
    # สุ่มเลือกประเภทและโซน 1 แบบในการรอบการทำงานนี้เพื่อลดการโดนแบน
    import random
    
    retries = 0
    total_scraped_session = 0
    total_skipped_session = 0
    total_saved_session = 0
    
    while retries < MAX_RETRIES:
        selected_type = random.choice(PROPERTY_TYPES)
        selected_zone = random.choice(TARGET_ZONES)
        
        print(f"\n--- Agent Action: Searching for '{selected_type}' in '{selected_zone}' (Attempt {retries + 1}/{MAX_RETRIES}) ---")

        # scraper agent will login (if session not exist), and scrape raw details from specific URLs
        scraped_listings = scraper.scrape_living_insider(target_url, property_type=selected_type, zone=selected_zone)
        
        if not scraped_listings: # Handles both None and []
            print(f"No property found for '{selected_type}' in '{selected_zone}' (ไม่พบข้อมูล). Instantly retrying...")
            retries += 1
            if retries >= MAX_RETRIES:
                print("Max retries reached. Exiting scraping phase.")
            continue
            
        print(f"\nCompleted Scraping Phase. Extracted details for {len(scraped_listings)} listings.")
        total_scraped_session += len(scraped_listings)
        
        # 3. Validation, Intelligence & Action Phases
        print("\n--- Validation, Intelligence & Storage Phases ---")
        
        new_records_added = 0
        skipped_records = 0
        
        for raw_data in scraped_listings:
            listing_id = raw_data.get("listing_id")
            
            if not listing_id:
                continue
                
            # A. Validation Phase (Firestore Check)
            if firestore.is_listing_exists(listing_id):
                print(f"SKIPPED ID {listing_id} - Already exists in Firestore.")
                skipped_records += 1
                continue
                
            print(f"\nPROCESSING NEW ID {listing_id} - Sending Detail Payload to Gemini...")
            
            # B. Intelligence Phase (Gemini Analysis)
            ai_evaluation = evaluator.evaluate_listing(raw_data)
            
            # C. Action Phase 1: Storage in Firestore (Main Storage)
            print(f"Saving ID {listing_id} to Firestore...")
            if firestore.save_listing(listing_id, raw_data, ai_evaluation):
                print(f"-> Saved ID {listing_id} to Firestore.")
            else:
                print(f"-> FAILED saving ID {listing_id} to Firestore.")
                
            # E. Action Phase 2: Delivery to Google Sheets (Dashboard Sync)
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # แยกราคาขาย/เช่า จาก Gemini analysis
            price_val = str(ai_evaluation.get("price", ""))
            is_rent = ai_evaluation.get("type", "").lower() == "เช่า" or "เช่า" in price_val
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Create ZIP and upload to Google Drive
            image_urls = raw_data.get("images", [])
            drive_link = "-"
            if image_urls:
                drive_link = drive.create_zip_and_upload_to_drive(image_urls, listing_id)

            # จัดลำดับข้อมูล 26 คอลัมน์ (เพิ่ม Column Y: โหลดรูป, Column Z: ประเภททรัพย์)
            row_to_append = [
                ai_evaluation.get("listing_date", "-"),      # 1. วันที่ลง (จากเว็บ) (A)
                "-",                                         # 2. วันที่โทร (B)
                "New",                                       # 3. สถานะการโทร (C)
                "-",                                         # 4. ขอสแกน (D)
                "-",                                         # 5. เข้าดูห้อง (E)
                "-",                                         # 6. วันที่เข้าดู (F)
                "-",                                         # 7. สแกน (G)
                "-",                                         # 8. รู้ทิศ (สแกนแล้ว) (H)
                "AI Scraper",                                # 9. ลงข้อมูล (I)
                "-",                                         # 10. วันนัดสแกน (J)
                ai_evaluation.get("project_name", "-"),      # 11. ชื่อโครงการ (จากเว็บ) (K)
                ai_evaluation.get("house_number", "-"),      # 12. เลขที่ห้อง (จากเว็บ) (L)
                ai_evaluation.get("floor", "-"),             # 13. ชั้น (จากเว็บ) (M)
                ai_evaluation.get("bed_bath", "-"),          # 14. Unit Type (จากเว็บ) (N)
                ai_evaluation.get("type", "-"),              # 15. S or R (จากเว็บ) (O)
                ai_evaluation.get("price", "-") if not is_rent else "-", # 16. ราคาขาย (จากเว็บ) (P)
                ai_evaluation.get("price", "-") if is_rent else "-",     # 17. ราคาเช่า (จากเว็บ) (Q)
                ai_evaluation.get("size", "-"),              # 18. Area (จากเว็บ) (R)
                ai_evaluation.get("phone_number", "-"),      # 19. เบอร์โทรเจ้าของ (จากเว็บ) (S)
                ai_evaluation.get("customer_name", "-"),     # 20. ชื่อเจ้าของ (จากเว็บ) (T)
                raw_data.get("url", ""),                     # 21. ลิงค์ (จากเว็บ) (U)
                "-",                                         # 22. Remark (V)
                "-",                                         # 23. Feedback (W)
                ai_evaluation.get("images_url", "-"),        # 24. ภาพห้อง (จากเว็บ) (X)
                drive_link,                                  # 25. โหลดรูป (Y)
                selected_type                                # 26. ประเภททรัพย์ (Z)
            ]
            
            # Sanitize Row Data: บังคับทุกช่องเป็น String ป้องกัน Error จาก Google Sheets API (กรณี AI ส่งค่า {} หรือ [] มา)
            clean_row_data = [str(val) if val is not None else "-" for val in row_to_append]
            
            print(f"Syncing ID {listing_id} to Google Sheets (26 Columns Mapping)...")
            if sheets.append_data(clean_row_data):
                new_records_added += 1
                print(f"-> SUCCESS synced ID {listing_id} to Google Sheets.")
            else:
                print(f"-> FAILED to sync ID {listing_id} to Google Sheets.")
                
        total_skipped_session += skipped_records
        total_saved_session += new_records_added
        
        # Check if we should stop
        if new_records_added > 0:
            print(f"Successfully scraped and saved {new_records_added} new records. Ending workflow.")
            break
        else:
            print("\nAll scraped listings this round were duplicates or failed to save (0 new records).")
            retries += 1
            if retries < MAX_RETRIES:
                print("Retrying with a new location/type...")
            else:
                print("Max retries reached. All found listings in recent rounds were duplicates.")

    # Final Report
    print(f"\n=== Workflow Completed ===")
    print(f"Total Scraped (Opened Detail Pages): {total_scraped_session}")
    print(f"Total Skipped (Already in DB): {total_skipped_session}")
    print(f"Total New Records Saved: {total_saved_session}")

if __name__ == "__main__":
    main()
