import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_location_details(project_name: str) -> dict:
    """
    ค้นหาพิกัดและที่อยู่จาก Google Geocoding API โดยอ้างอิงจากชื่อ project_name
    """
    api_key = os.getenv('PROPERTY_SCRAPER_MAPS_KEY') or os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        print("  [Maps] ไม่พบ API Key (PROPERTY_SCRAPER_MAPS_KEY) ข้ามการค้นหาแผนที่")
        return {}
        
    if not project_name or project_name == "-":
        return {}
        
    print(f"🗺️ [Places API NEW] กำลังสืบค้นข้อมูลพิกัดสถานที่จากชื่อโครงการ: '{project_name}'...")
    
    # 🎯 ใช้ Google Places API (New - v1) ซึ่งประหยัดและแม่นยำกว่า
    url = "https://places.googleapis.com/v1/places:searchText"
    
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.addressComponents"
    }
    
    payload = {
        "textQuery": project_name,
        "languageCode": "th",
        "regionCode": "th"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("places") and len(data["places"]) > 0:
            place = data["places"][0]
            
            location_info = {
                "address": place.get("formattedAddress", ""),
                "latitude": str(place["location"]["latitude"]),
                "longitude": str(place["location"]["longitude"]),
                "state": "",
                "city": "",
                "sub_district": "",
                "postal_code": "",
                "country": ""
            }
            
            # --- [NEW] ดึง Address Components จากคำตอบเดียวได้เลย (ไม่ต้องยิงซ้ำ!) ---
            for comp in place.get("addressComponents", []):
                types = comp.get("types", [])
                long_name = comp.get("longText", "")
                
                if "administrative_area_level_1" in types: 
                    location_info["state"] = long_name
                elif "locality" in types or "administrative_area_level_2" in types or "sublocality_level_1" in types: 
                    # 🏙️ พยายามดึงเขต/อำเภอ (ถ้าเป็น กทม. บางทีจะเป็น sublocality_level_1)
                    if not location_info["city"] or "administrative_area_level_2" in types:
                        location_info["city"] = long_name
                elif "sublocality" in types: 
                    location_info["sub_district"] = long_name
                elif "postal_code" in types: 
                    location_info["postal_code"] = long_name
                elif "country" in types: 
                    location_info["country"] = long_name

            print(f"  [Maps] ✅ ค้นพบพิกัดสำเร็จ (New API): {location_info['latitude']}, {location_info['longitude']}")
            return location_info
        else:
            print(f"  [Maps] ⚠️ ไม่พบสถานที่จากชื่อโครงการนี้ (Status: Empty Response)")
            return {}
            
    except Exception as e:
        print(f"  [Maps] ❌ เกิดข้อผิดพลาดในการดึงข้อมูลจาก Places API (New): {e}")
        return {}
