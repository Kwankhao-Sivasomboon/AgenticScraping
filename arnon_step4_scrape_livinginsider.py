import os
import re
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
# from google.cloud.firestore_v1.base_query import FieldFilter

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()

def extract_livinginsider_data(url):
    """
    ดึงข้อมูลจากเว็บไซต์ LivingInsider
    คืนค่าเป็น dict พร้อมข้อมูล: built_year, project_name, address, num_buildings, max_floors, total_units
    หรือ None ถ้าไม่พบข้อมูล
    """
    if "livinginsider.com" not in url.lower():
        print(f"      [!] ไม่ใช่ลิงก์ LivingInsider: {url}")
        return None
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"      [!] Request failed with status {r.status_code}")
            return None
            
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # ค้นหา <div class='box-show-text-all-project'> ทื่เก็บข้อมูลสรุปโครงการ
        target_div = soup.find('div', class_='box-show-text-all-project')
        
        if not target_div:
            print("      [!] ไม่พบ <div class='box-show-text-all-project'> ในหน้านี้")
            return None
            
        text = target_div.get_text(separator=' ', strip=True)
        print(f"      📄 Raw text: {text}")
        
        result = {}
        
        # 1. หารหัสปีที่สร้างเสร็จ
        year_match = re.search(r'สร้างเสร็จปี\s*(\d{4})', text)
        if year_match:
            result['built_year'] = int(year_match.group(1))
            
        # 2. หาชื่อโครงการ
        name_match = re.search(r'ข้อมูลเกี่ยวกับโครงการ\s+(.*?)\s+มีสถานที่ตั้งโครงการอยู่ที่', text)
        if name_match:
            result['project_name'] = name_match.group(1).strip()
            
        # 3. หาที่อยู่
        address_match = re.search(r'มีสถานที่ตั้งโครงการอยู่ที่\s+(.*?)(?=\s+จำนวนอาคาร|\s+สร้างเสร็จปี|$)', text)
        if address_match:
            result['address'] = address_match.group(1).strip()

        # 4. จำนวนอาคาร (Building count)
        building_match = re.search(r'จำนวนอาคารในโครงการนี้มีทั้งหมด\s*(\d+)\s*อาคาร', text)
        if building_match:
            result['num_buildings'] = int(building_match.group(1))

        # 5. ความสูงชั้น (Floor count/Height)
        floor_match = re.search(r'มีความสูง\s*(\d+)\s*ชั้น', text)
        if floor_match:
            result['max_floors'] = int(floor_match.group(1))

        # 6. จำนวนยูนิตทั้งหมด (Total Units)
        unit_match = re.search(r'มีจำนวนห้องพักอาศัยจำนวน\s*(\d+)\s*ยูนิต', text)
        if unit_match:
            result['total_units'] = int(unit_match.group(1))
            
        return result
        
    except Exception as e:
        print(f"      [!] Scraping Error: {e}")
        return None

def main():
    fs = FirestoreService()
    print("🚀 เริ่มสแกนคิวงานจาก 'Leads' ทั้งหมดเพื่อดึงข้อมูล LivingInsider ( built_year, address, floors, units, buildings )...")
    
    lead_docs = fs.db.collection("Leads").get()
    count_updated = 0
    
    for lead_doc in lead_docs:
        prop_id = lead_doc.id
        lead_ref = lead_doc.reference
        lead_data = lead_doc.to_dict()

        # ถ้ามีข้อมูลครบแล้ว (ปีที่สร้าง + ยูนิต + ชั้น) ให้ข้ามเพื่อประหยัดเวลา
        if lead_data.get("built_year") and lead_data.get("scraped_max_floors") and lead_data.get("scraped_total_units"):
            continue
            
        # 1. ดึง Link
        target_url = lead_data.get("sheet_ลิงค์") or lead_data.get("url")
        
        if not target_url or "livinginsider" not in str(target_url).lower():
            # print(f"⚠️ Skip {prop_id}: ไม่ใช่ลิงก์ LivingInsider")
            continue
            
        print(f"\n🏢 Property ID: {prop_id} | URL: {target_url}")
        scraped_data = extract_livinginsider_data(target_url)
        
        if scraped_data:
            print(f"   🎉 พบข้อมูล: {scraped_data}")
            
            update_payload = {}
            if "built_year" in scraped_data:
                update_payload["built_year"] = scraped_data["built_year"]
            if "project_name" in scraped_data:
                update_payload["scraped_project_name"] = scraped_data["project_name"]
            if "address" in scraped_data:
                update_payload["scraped_address"] = scraped_data["address"]
            if "num_buildings" in scraped_data:
                update_payload["scraped_num_buildings"] = scraped_data["num_buildings"]
            if "max_floors" in scraped_data:
                update_payload["scraped_max_floors"] = scraped_data["max_floors"]
            if "total_units" in scraped_data:
                update_payload["scraped_total_units"] = scraped_data["total_units"]
                
            lead_ref.update(update_payload)
            count_updated += 1
        else:
            print(f"   ❌ ไม่พบข้อมูลเป้าหมายในลิงก์นี้")
                
        time.sleep(1.5)

    print(f"\n✅ ทำงานเสร็จสิ้น: อัปเดตข้อมูลสำเร็จทั้งหมด {count_updated} รายการ")

if __name__ == "__main__":
    main()
