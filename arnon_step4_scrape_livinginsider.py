import os
import re
import time
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.cloud.firestore_v1.base_query import FieldFilter

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()

def extract_livinginsider_data(url):
    """
    ดึงข้อมูลจากเว็บไซต์ LivingInsider
    คืนค่าเป็น dict: { "built_year": int, "project_name": str, "address": str }
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
        
        # เนื่องจากเราดึงโค้ด HTML มาโดยตรง (ไม่ได้ผ่าน Browser สด)
        # ข้อมูลที่ซ่อนอยู่ (display: none) ใน box-show-text-all-project จะยังคงอยู่ใน Source Code
        target_div = soup.find('div', class_='box-show-text-all-project')
        
        if not target_div:
            print("      [!] ไม่พบ <div class='box-show-text-all-project'> ในหน้านี้")
            return None
            
        text = target_div.get_text(separator=' ', strip=True)
        print(f"      📄 Raw text: {text}")
        
        result = {}
        
        # 1. หารหัสปีที่สร้างเสร็จ
        # สร้างเสร็จปี 2018
        year_match = re.search(r'สร้างเสร็จปี\s*(\d{4})', text)
        if year_match:
            result['built_year'] = int(year_match.group(1))
            
        # 2. หาชื่อโครงการ
        # ข้อมูลเกี่ยวกับโครงการ [ชื่อ] มีสถานที่ตั้งโครงการอยู่ที่
        name_match = re.search(r'ข้อมูลเกี่ยวกับโครงการ\s+(.*?)\s+มีสถานที่ตั้งโครงการอยู่ที่', text)
        if name_match:
            result['project_name'] = name_match.group(1).strip()
            
        # 3. หาที่อยู่
        # มีสถานที่ตั้งโครงการอยู่ที่ [ที่อยู่] จำนวนอาคาร
        # หรือไปจนจบประโยคถ้าไม่มีคำว่า จำนวนอาคาร
        address_match = re.search(r'มีสถานที่ตั้งโครงการอยู่ที่\s+(.*?)(?=\s+จำนวนอาคาร|\s+สร้างเสร็จปี|$)', text)
        if address_match:
            result['address'] = address_match.group(1).strip()
            
        return result
        
    except Exception as e:
        print(f"      [!] Scraping Error: {e}")
        return None

def main():
    fs = FirestoreService()
    print("🚀 เริ่มสแกนคิวงานจาก 'Leads' ทั้งหมด (ไม่สนใจ Status) เพื่อดึงข้อมูล LivingInsider...")
    
    lead_docs = fs.db.collection("Leads").get()
    count_updated = 0
    
    for lead_doc in lead_docs:
        prop_id = lead_doc.id
        lead_ref = lead_doc.reference
        lead_data = lead_doc.to_dict()

        # ป้องกันการทำซ้ำ ถ้ามี built_year เป็นตัวเลขแล้วให้ข้าม (เปลี่ยนบรรทัดนี้ได้ถ้าอยากให้เขียนทับที่อยู่ด้วย)
        if lead_data.get("built_year") is not None and lead_data.get("scraped_address"):
            continue
            
        # 1. ดึง Link
        target_url = lead_data.get("sheet_ลิงค์") or lead_data.get("url")
        
        if not target_url or "livinginsider" not in str(target_url).lower():
            print(f"⚠️ Skip {prop_id}: ไม่ใช่ลิงก์ LivingInsider หรือไม่มีลิงก์")
            # lead_ref.update({"built_year": None})
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
                
            lead_ref.update(update_payload)
            count_updated += 1
        else:
            print(f"   ❌ ไม่พบข้อมูลเป้าหมายในลิงก์นี้")
            # ลองบันทึกว่าหาไม่เจอ
            if lead_data.get("built_year") is None:
                lead_ref.update({"built_year": None})
                
        time.sleep(2)

    print(f"\n✅ ทำงานเสร็จสิ้น: อัปเดตข้อมูลสำเร็จทั้งหมด {count_updated} รายการ")

if __name__ == "__main__":
    main()
