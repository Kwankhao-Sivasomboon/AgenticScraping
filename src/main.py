import os
import sys
import re
from datetime import datetime

# Ensure project root is in the python path to support 'src.' imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from src.agents.scraper_agent import ScraperAgent
from src.agents.evaluator_agent import EvaluatorAgent
from src.services.firestore_service import FirestoreService
from src.services.storage_service import StorageService
from src.services.sheets_service import SheetsService
from src.services.geocoding_service import GeocodingService

def init_services():
    try:
        from src.config import DEBUG_MODE
        scraper = ScraperAgent()
        evaluator = EvaluatorAgent()
        firestore = FirestoreService()
        storage_svc = StorageService()
        geocoding = GeocodingService()
        
        sheets = None
        if DEBUG_MODE:
            try:
                sheets = SheetsService()
            except Exception as se:
                print(f"⚠️ SheetsService initialization failed: {se}")
    except Exception as e:
        print(f"Error initializing services: {e}")
        return None

    return {
        "scraper": scraper,
        "evaluator": evaluator,
        "firestore": firestore,
        "storage_svc": storage_svc,
        "geocoding": geocoding,
        "sheets": sheets
    }

def run_scraping_job(selected_type, selected_zone, max_items_override=None):
    from src.config import MAX_RETRIES
    import src.config as config
    
    if max_items_override is not None:
        config.MAX_ITEMS_PER_RUN = max_items_override

    services = init_services()
    if not services:
        return {"error": "Failed to initialize services"}
        
    scraper = services["scraper"]
    evaluator = services["evaluator"]
    firestore = services["firestore"]
    storage_svc = services["storage_svc"]
    geocoding = services["geocoding"]
    sheets = services["sheets"]
    
    from src.config import DEBUG_MODE
    print(f"🔧 Mode: {'DEBUG (Google Sheets)' if DEBUG_MODE else 'PRODUCTION (Agent API)'}")

    # 2. Ingestion Phase: Scraper Agent 
    print(f"\n--- Ingestion Phase: '{selected_type}' in '{selected_zone}' ---")
    target_url = "https://www.livinginsider.com/?srsltid=AfmBOooDgW_K_dldNP20QHs4sLi2OMdto01GWcucYKCxjlSbubJaGHqe"
    
    retries = 0
    total_scraped_session = 0
    total_skipped_session = 0
    total_saved_session = 0
    
    while retries < MAX_RETRIES:
        print(f"\n--- Agent Action: Searching for '{selected_type}' in '{selected_zone}' (Attempt {retries + 1}/{MAX_RETRIES}) ---")

        # scraper agent will login (if session not exist), and scrape raw details from specific URLs
        scraped_listings = scraper.scrape_living_insider(target_url, property_type=selected_type, zone=selected_zone)
        
        print("\n--- Processing Phase (Real-time Scraping & Saving) ---")
        
        new_records_added = 0
        skipped_records = 0
        has_items = False

        
        for raw_data in scraped_listings:
            has_items = True
            total_scraped_session += 1
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
            
            # --- [Google Maps API Geocoding as fallback] ---
            lat = ai_evaluation.get("latitude")
            lon = ai_evaluation.get("longitude")
            if (not lat or str(lat) == "-") and (not lon or str(lon) == "-"):
                address_query = f"{ai_evaluation.get('project_name', '')} {ai_evaluation.get('address', '')} {ai_evaluation.get('city', '')} {selected_zone}".strip()
                g_lat, g_lon = geocoding.get_coordinates(address_query)
                if g_lat and g_lon:
                    ai_evaluation["latitude"] = g_lat
                    ai_evaluation["longitude"] = g_lon
            
            price_sell = ai_evaluation.get("price_sell", "-")
            price_rent = ai_evaluation.get("price_rent", "-")
            
            # --- [Final Guard] คัดกรองราคาสูงสุดอีกครั้งหลัง AI วิเคราะห์เสร็จ ---
            from src.config import MAX_PRICE_LIMITS
            limit = MAX_PRICE_LIMITS.get(selected_type, 10000000) # Default 10M if unknown
            
            def parse_final_price(p_val):
                if p_val is None or p_val == "-": return 0
                if isinstance(p_val, (int, float)): return float(p_val)
                
                p_str = str(p_val).lower().replace(",", "").strip()
                # จับคู่ตัวเลขและหน่วย (ล้าน, m, k)
                matches = re.finditer(r'(\d+(?:\.\d+)?)\s*([ลล้านmk]*)', p_str)
                
                prices = []
                for m in matches:
                    val = float(m.group(1))
                    unit = m.group(2)
                    
                    if 'ล' in unit or 'ล้าน' in unit or 'm' in unit:
                        val *= 1000000
                    elif 'k' in unit:
                        val *= 1000
                    # ถ้าตัวเลขน้อยเกินไป (เช่น 1-50) และไม่มีหน่วย แต่เป็นบ้าน/คอนโด ให้เดาว่าเป็น "ล้าน"
                    elif val < 1000 and val > 0:
                        val *= 1000000
                        
                    prices.append(val)
                
                return max(prices) if prices else 0

            final_sell_price = parse_final_price(ai_evaluation.get("price_sell"))
            final_rent_price = parse_final_price(ai_evaluation.get("price_rent"))
            
            # เช็คราคาสูงสุดจากทั้งสองช่อง
            highest_actual_price = max(final_sell_price, final_rent_price)

            if highest_actual_price > limit:
                print(f"🚫 [Final Skip] {listing_id} พบราคาสูงสุด {highest_actual_price:,.0f} เกินงบ {limit:,.0f}. (ข้ามการบันทึก)")
                skipped_records += 1
                continue
            # -----------------------------------------------------------------

            # --- DATA STORAGE SELECTION (DEBUG vs PRODUCTION) ---
            if DEBUG_MODE:
                # 1. Option A: Save to Google Sheets (Debug)
                print(f"📊 [Debug] Saving to Google Sheet (26 Columns) for {listing_id}...")
                if sheets:
                    # ปรับโครงสร้าง Rows ให้ตรงกับ 26 คอลัมน์ที่คุณต้องการ
                    # 1.วันที่ลง, 2.วันที่โทร, 3.สถานะการโทร, 4.ขอสแกน, 5.เข้าดูห้อง, 6.วันที่เข้าดู, 7.สแกน,
                    # 8.รู้ทิศ, 9.ลงข้อมูล, 10.วันนัดสแกน, 11.ชื่อโครงการ, 12.เลขที่ห้อง, 13.ชั้น,
                    # 14.Unit Type, 15.S or R, 16.ราคาขาย, 17.ราคาเช่า, 18.Area, 19.เบอร์โทรเจ้าของ,
                    # 20.ชื่อเจ้าของ, 21.ลิงค์, 22.Remark, 23.Feedback, 24.ภาพห้อง, 25.โหลดรูป, 26.ประเภททรัพย์
                    
                    images = raw_data.get("images", [])
                    first_image = images[0] if images else "-"
                    
                    sheet_row = [
                        datetime.now().strftime("%Y-%m-%d"), # 1. วันที่ลง
                        "-", # 2. วันที่โทร
                        "-", # 3. สถานะการโทร
                        "-", # 4. ขอสแกน
                        "-", # 5. เข้าดูห้อง
                        "-", # 6. วันที่เข้าดู
                        "-", # 7. สแกน
                        ai_evaluation.get("direction", "ไม่ระบุทิศ"), # 8. รู้ทิศ
                        "-", # 9. ลงข้อมูล
                        "-", # 10. วันนัดสแกน
                        ai_evaluation.get("project_name", "-"), # 11. ชื่อโครงการ
                        ai_evaluation.get("house_number", "-"), # 12. เลขที่ห้อง
                        ai_evaluation.get("floor", "-"),        # 13. ชั้น
                        ai_evaluation.get("bed_bath", "-"),     # 14. Unit Type
                        ai_evaluation.get("type", "-"),         # 15. S or R
                        ai_evaluation.get("price_sell", "-"),   # 16. ราคาขาย
                        ai_evaluation.get("price_rent", "-"),   # 17. ราคาเช่า
                        ai_evaluation.get("size", "-"),         # 18. Area
                        ai_evaluation.get("phone_number", "-"), # 19. เบอร์โทรเจ้าของ
                        ai_evaluation.get("customer_name", "-"), # 20. ชื่อเจ้าของ 
                        raw_data.get("url", "-"),               # 21. ลิงค์ (Column U)
                        "-", # 22. Remark
                        "-", # 23. Feedback
                        first_image, # 24. ภาพห้อง
                        "-", # 25. โหลดรูป
                        selected_type, # 26. ประเภททรัพย์
                        selected_zone # 27. โซน (Zone - Column AA)
                    ]
                    sheets.append_data(sheet_row)
                    print(f"✅ Data appended to Google Sheets (U={raw_data.get('url')[:30]}...)")
                else:
                    print("❌ Sheets service not available. Check credentials.")
            else:
                print(f"🏠 [Production] Data will only be saved to Firestore. (Use sync_to_api.py to push to Agent API)")
            
            # --- ALWAYS SAVE TO FIRESTORE (As History) ---
            # แนบ zone และ property_type เข้าไปใน raw_data ก่อนบันทึก
            raw_data['zone'] = selected_zone
            raw_data['property_type'] = selected_type
            print(f"💾 Saving ID {listing_id} to Firestore tracking... (zone={selected_zone}, type={selected_type})")
            if firestore.save_listing(listing_id, raw_data, ai_evaluation):
                print(f"-> Saved ID {listing_id} to Firestore.")
            else:
                print(f"-> FAILED saving ID {listing_id} to Firestore.")
                
            new_records_added += 1
            print(f"-> WORKFLOW COMPLETED FOR {listing_id}.")
                
        total_skipped_session += skipped_records
        total_saved_session += new_records_added
        
        if not has_items:
            print(f"No property found or all items skipped for '{selected_type}' in '{selected_zone}'. Instantly retrying...")
            retries += 1
            if retries >= MAX_RETRIES:
                print("Max retries reached. Exiting scraping phase.")
            continue
        
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
    print(f"Total Scraped: {total_scraped_session}")
    print(f"Total Skipped: {total_skipped_session}")
    print(f"Total Saved: {total_saved_session}")
    
    return {
        "status": "success",
        "scraped": total_scraped_session,
        "skipped": total_skipped_session,
        "saved": total_saved_session
    }

def main():
    start_time = datetime.now()
    print("=== Starting Agentic AI Scraping Workflow (Detailed Hybrid) ===")
    from src.config import PROPERTY_TYPES, TARGET_ZONES
    
    total_types = len(PROPERTY_TYPES)
    total_zones = len(TARGET_ZONES)
    total_jobs = total_types * total_zones
    print(f"📌 วางแผนดึงข้อมูลแบบเรียงลำดับ: {total_types} ประเภทอสังหาฯ x {total_zones} โซน = {total_jobs} รอบทั้งหมด")
    
    current_job = 1
    for selected_type in PROPERTY_TYPES:
        for selected_zone in TARGET_ZONES:
            print(f"\n=======================================================")
            print(f"🚀 เริ่มคิวที่ {current_job}/{total_jobs}: ประเภท '{selected_type}' | โซน '{selected_zone}'")
            print(f"=======================================================")
            run_scraping_job(selected_type, selected_zone)
            current_job += 1
    
    end_time = datetime.now()
    elapsed_time = end_time - start_time
    # แปลงเป็น นาที:วินาที ให้อ่านง่าย
    minutes, seconds = divmod(elapsed_time.total_seconds(), 60)
    print(f"\n⏱️ เวลาที่ใช้ในการทำงานทั้งหมด: {int(minutes)} นาที {seconds:.2f} วินาที")

if __name__ == "__main__":
    main()
