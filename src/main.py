from datetime import datetime
from sheets_service import SheetsService
from scraper_agent import ScraperAgent
from evaluator_agent import EvaluatorAgent
from firestore_service import FirestoreService

def main():
    print("=== Starting Agentic AI Scraping Workflow (Detailed Hybrid) ===")
    
    # 1. Initialize Services
    try:
        sheets = SheetsService()
        scraper = ScraperAgent()
        evaluator = EvaluatorAgent()
        firestore = FirestoreService()
    except Exception as e:
        print(f"Error initializing services: {e}")
        return

    # 2. Ingestion Phase: Scraper Agent 
    print("\n--- Ingestion Phase ---")
    # For testing, we are just executing the scraper setup directly with Playwright 
    target_url = "https://www.livinginsider.com/?srsltid=AfmBOooDgW_K_dldNP20QHs4sLi2OMdto01GWcucYKCxjlSbubJaGHqe"
    
    # You can now specify property type and zone using a Random Pick strategy
    property_types = ['บ้าน', 'คอนโด', 'ทาวน์โฮม', 'อพาร์ตเมนต์', 'พูลวิลล่า']
    target_zones = ['สุขุมวิท', 'พระโขนง', 'อ่อนนุช', 'สำโรง', 'แบริ่ง', 'ปุณณวิถี']
    
    # สุ่มเลือกประเภทและโซน 1 แบบในการรอบการทำงานนี้เพื่อลดการโดนแบน
    import random
    
    max_retries = 3
    retries = 0
    total_scraped_session = 0
    total_skipped_session = 0
    total_saved_session = 0
    
    while retries < max_retries:
        selected_type = random.choice(property_types)
        selected_zone = random.choice(target_zones)
        
        print(f"\n--- Agent Action: Searching for '{selected_type}' in '{selected_zone}' (Attempt {retries + 1}/{max_retries}) ---")

        # scraper agent will login (if session not exist), and scrape raw details from specific URLs
        scraped_listings = scraper.scrape_living_insider(target_url, property_type=selected_type, zone=selected_zone)
        
        if not scraped_listings: # Handles both None and []
            print(f"No property found for '{selected_type}' in '{selected_zone}' (ไม่พบข้อมูล). Instantly retrying...")
            retries += 1
            if retries >= max_retries:
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
            
            row_to_append = [
                current_time,                             # วันที่ลง
                "-",                                      # วันที่โทร (รอคนเติม)
                "AI Scraper",                             # ลงข้อมูล
                "New",                                    # สถานะการโทร
                "-",                                      # เข้าไปได้ไหม
                "-",                                      # แจ้งจะเข้า
                ai_evaluation.get("floor", "-"),          # ชั้น
                ai_evaluation.get("project_name", "-"),   # ชื่อโครงการ
                ai_evaluation.get("bed_bath", "-"),       # Unit Type
                ai_evaluation.get("price", "-") if not is_rent else "-", # ราคาขาย
                ai_evaluation.get("price", "-") if is_rent else "-",     # ราคาเช่า
                ai_evaluation.get("type", "-"),           # SorR (Sale or Rent)
                ai_evaluation.get("size", "-"),           # SQM
                ai_evaluation.get("house_number", "-"),   # เลขที่ห้อง
                ai_evaluation.get("phone_number", "-"),   # เบอร์โทรเจ้าของ
                ai_evaluation.get("line_id", "-"),        # Line ID
                ai_evaluation.get("email", "-"),          # Email
                ai_evaluation.get("customer_name", "-"),  # ชื่อเจ้าของ
                raw_data.get("url", ""),                  # ลิงค์
                ai_evaluation.get("images_url", "-")      # ภาพห้อง
            ]
            
            print(f"Syncing ID {listing_id} to Google Sheets (LivingInsider)...")
            if sheets.append_data(row_to_append):
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
            if retries < max_retries:
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
