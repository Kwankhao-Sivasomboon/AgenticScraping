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
from src.services.api_service import APIService
from src.services.geocoding_service import GeocodingService
from src.utils.image_processor import ImageService

def init_services():
    try:
        from src.config import DEBUG_MODE
        scraper = ScraperAgent()
        evaluator = EvaluatorAgent()
        firestore = FirestoreService()
        storage_svc = StorageService()
        api = APIService()
        geocoding = GeocodingService()
        image_svc = ImageService()
        
        sheets = None
        if DEBUG_MODE:
            try:
                sheets = SheetsService()
            except Exception as se:
                print(f"⚠️ SheetsService initialization failed: {se}")
        
        # Only authenticate if we are NOT in debug mode (Production)
        if not DEBUG_MODE:
            api.authenticate()
        else:
            print("🧪 [Debug] Skipping Agent API Authentication...")
    except Exception as e:
        print(f"Error initializing services: {e}")
        return None

    return {
        "scraper": scraper,
        "evaluator": evaluator,
        "firestore": firestore,
        "storage_svc": storage_svc,
        "api": api,
        "geocoding": geocoding,
        "image_svc": image_svc,
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
    api = services["api"]
    geocoding = services["geocoding"]
    image_svc = services["image_svc"]
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
            limit = MAX_PRICE_LIMITS.get(selected_type, 999999999)
            
            def parse_final_price(p_str):
                if not p_str or p_str == "-": return 0
                clean = str(p_str).replace(",", "").replace("/", "").strip()
                matches = re.findall(r'(\d+(?:\.\d+)?)', clean)
                if not matches: return 0
                
                # กวาดทุกตัวเลขที่เจอแล้วหาค่า MAX (กันกรณี Sale & Rent แล้วตัวเลขราคาเช่าโผล่มาตัวแรก)
                p_vals = []
                for m in matches:
                    val = float(m)
                    if "ล้าน" in str(p_str): val *= 1000000
                    p_vals.append(val)
                return max(p_vals) if p_vals else 0

            final_sell_price = parse_final_price(price_sell)
            final_rent_price = parse_final_price(price_rent)
            
            # เช็คราคาสูงสุดจากทั้งสองช่อง (เผื่อ Gemini ใส่สลับกันมา)
            highest_actual_price = max(final_sell_price, final_rent_price)

            if highest_actual_price > limit:
                print(f"🚫 [Final Skip] {listing_id} พบราคาสูงสุด {highest_actual_price:,.0f} เกินงบ {limit:,.0f}. (ข้ามการบันทึก)")
                skipped_records += 1
                continue
            # -----------------------------------------------------------------

            # --- PREPARE DATA PAYLOAD ---
            date_val = ai_evaluation.get("listing_date", "")
            if date_val == "-" or not date_val:
                date_val = datetime.now().strftime("%Y-%m-%d")

            payload = {
                "built": date_val,
                "name": ai_evaluation.get("project_name") if ai_evaluation.get("project_name") != "-" else f"Listing {listing_id}",
                "type": "condo" if "คอนโด" in selected_type else "house",
                "status": "available",
                "price": final_sell_price if final_sell_price > 0 else 0,
                "monthly_rental_price": final_rent_price if final_rent_price > 0 else 0,
                "description": raw_data.get("raw_text", "-")[:4000], 
                "address": ai_evaluation.get("address", "-"),
                "number": ai_evaluation.get("house_number", "-"),
                "city": ai_evaluation.get("city", "-"),
                "postal_code": ai_evaluation.get("postal_code", "-"),
                "latitude": str(ai_evaluation.get("latitude", "")),
                "longitude": str(ai_evaluation.get("longitude", "")),
                "specifications": ai_evaluation.get("specifications", {}),
                "specification_values": ai_evaluation.get("specification_values", {})
            }

            # --- DATA STORAGE SELECTION (DEBUG vs PRODUCTION) ---
            if DEBUG_MODE:
                # 1. Option A: Save to Google Sheets (Debug)
                print(f"📊 [Debug] Saving to Google Sheet for {listing_id}...")
                if sheets:
                    # Prepare row data (Ordering based on your previous sheet structure)
                    sheet_row = [
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        listing_id,
                        raw_data.get("url", "-"),
                        ai_evaluation.get("project_name", "-"),
                        ai_evaluation.get("price_sell", "-"),
                        ai_evaluation.get("price_rent", "-"),
                        ai_evaluation.get("customer_name", "-"),
                        ai_evaluation.get("phone_number", "-"),
                        ai_evaluation.get("line_id", "-"),
                        ai_evaluation.get("type", "-"),
                        ai_evaluation.get("size", "-"),
                        ai_evaluation.get("bed_bath", "-"),
                        ai_evaluation.get("address", "-"),
                        selected_zone,
                        "DEBUG_MODE"
                    ]
                    sheets.append_data(sheet_row)
                    print(f"✅ Data appended to Google Sheets.")
                else:
                    print("❌ Sheets service not available. Check credentials.")
            else:
                # 2. Option B: Save to Agent API (Production)
                print(f"🏠 [Production] Creating property in API for {listing_id}...")
                property_id = api.create_property(payload)
                if not property_id:
                    print(f"⚠️ [Note] API Offline/Failed - Skip property creation.")
                else:
                    ai_evaluation['api_property_id'] = property_id
                
                # --- IMAGE PROCESSING & UPLOAD (Only for API Mode) ---
                image_urls = raw_data.get("images", [])
                if image_urls and property_id:
                    processed_photos = image_svc.process_images(image_urls)
                    if processed_photos:
                        api.upload_photos(property_id, processed_photos)
                        print(f"✅ Images successfully attached to Property ID: {property_id}")
            
            # --- ALWAYS SAVE TO FIRESTORE (As History) ---
            print(f"💾 Saving ID {listing_id} to Firestore tracking...")
            if firestore.save_listing(listing_id, raw_data, ai_evaluation):
                print(f"-> Saved ID {listing_id} to Firestore.")
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
    print("=== Starting Agentic AI Scraping Workflow (Detailed Hybrid) ===")
    from src.config import PROPERTY_TYPES, TARGET_ZONES
    import random
    selected_type = random.choice(PROPERTY_TYPES)
    selected_zone = random.choice(TARGET_ZONES)
    run_scraping_job(selected_type, selected_zone)

if __name__ == "__main__":
    main()
