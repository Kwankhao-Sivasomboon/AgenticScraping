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
        
    print(f"🗺️ [Maps Service] กำลังสืบค้นข้อมูลพิกัดสถานที่จากชื่อโครงการ: '{project_name}'...")
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    
    params = {
        "address": project_name,
        "key": api_key,
        "language": "th",  # ภาษาไทย
        "region": "th"
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "OK" and len(data.get("results", [])) > 0:
            result = data["results"][0]
            
            location_info = {
                "address": result.get("formatted_address", ""),
                "latitude": str(result["geometry"]["location"]["lat"]),
                "longitude": str(result["geometry"]["location"]["lng"]),
                "state": "",
                "city": "",
                "sub_district": "",
                "postal_code": "",
                "country": ""
            }
            
            # แปลง Address Components
            for comp in result.get("address_components", []):
                types = comp.get("types", [])
                long_name = comp.get("long_name", "")
                
                if "administrative_area_level_1" in types:  # จังหวัด (State/Province)
                    location_info["state"] = long_name
                elif "locality" in types or "administrative_area_level_2" in types:  # เขต/อำเภอ (City/District)
                    location_info["city"] = long_name
                elif "sublocality" in types or "sublocality_level_1" in types: # แขวง/ตำบล (Sub-district)
                    location_info["sub_district"] = long_name
                elif "postal_code" in types:
                    location_info["postal_code"] = long_name
                elif "country" in types:
                    location_info["country"] = long_name
            
            print(f"  [Maps] ✅ ค้นพบพิกัดสำเร็จ: {location_info['latitude']}, {location_info['longitude']}")
            return location_info
        else:
            print(f"  [Maps] ⚠️ ไม่พบสถานที่จากชื่อโครงการนี้ (Status: {data.get('status')})")
            return {}
            
    except Exception as e:
        print(f"  [Maps] ❌ เกิดข้อผิดพลาดในการดึงข้อมูลจาก Maps API: {e}")
        return {}
