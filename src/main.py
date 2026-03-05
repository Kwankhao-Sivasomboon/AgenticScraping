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
    
    # scraper agent will login (if session not exist), and scrape raw details from specific URLs
    scraped_listings = scraper.scrape_living_insider(target_url)
    print(f"\nCompleted Scraping Phase. Extracted details for {len(scraped_listings)} listings.")

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
            
        # D. Action Phase 2: Delivery to Google Sheets (Dashboard Sync)
        # Expected Google Sheets Columns in order:
        # [Date, ListingID, URL, Type, Price, Size, BedBath, Floor, HouseNumber, Name, Phone, LeadScore, Images]
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_to_append = [
            current_time,
            listing_id,
            raw_data.get("url", ""),
            ai_evaluation.get("type", ""),
            ai_evaluation.get("price", ""),
            ai_evaluation.get("size", ""),
            ai_evaluation.get("bed_bath", ""),
            ai_evaluation.get("floor", ""),
            ai_evaluation.get("house_number", ""),
            ai_evaluation.get("customer_name", ""),
            ai_evaluation.get("phone_number", ""),
            ai_evaluation.get("lead_score", 0),
            ai_evaluation.get("images_url", "")
        ]
        
        print(f"Syncing ID {listing_id} to Google Sheets Dashboard...")
        if sheets.append_data(row_to_append):
            new_records_added += 1
            print(f"-> SUCCESS synced ID {listing_id} to Google Sheets.")
        else:
            print(f"-> FAILED to sync ID {listing_id} to Google Sheets.")
            
    # Final Report
    print(f"\n=== Workflow Completed ===")
    print(f"Total Scraped (Opened Detail Pages): {len(scraped_listings)}")
    print(f"Total Skipped (Already in DB): {skipped_records}")
    print(f"Total New Records Saved: {new_records_added}")

if __name__ == "__main__":
    main()
