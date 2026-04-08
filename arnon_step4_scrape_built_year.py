import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from googlesearch import search
from dotenv import load_dotenv

import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from google.cloud.firestore_v1.base_query import FieldFilter
from src.services.firestore_service import FirestoreService

load_dotenv()

def scrape_zmyhome_year(project_name):
    # เพิ่มคำว่า 'โครงการ' เข้าไปเพื่อให้ Google จัดลำดับหน้า Project Info ขึ้นมาก่อนหน้ารวมประกาศ
    query = f"site:zmyhome.com \"{project_name}\" โครงการ"
    url = None
    
    try:
        print(f"      🔎 Searching Google: '{query}'")
        # สุ่มดีเลย์เล็กน้อยก่อนยิง request เพื่อลดโอกาสโดนบล็อก
        time.sleep(random.uniform(1.0, 3.0))
        # ค้นหาเพิ่มเป็น 10 รายการเพื่อให้ครอบคลุมตัวเลือกที่ดีที่สุด
        for j in search(query, num_results=10, lang="th"):
            # เงื่อนไข: ต้องมี /project/ และต้องไม่มี /project-list/ (หน้ารวมประกาศ)
            if "zmyhome.com" in j and "/project/" in j and "/project-list/" not in j:
                url = j
                break
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "Too Many Requests" in err_msg:
            raise  # โยน Error 429 ไปให้ main() จัดการ
        print(f"      [!] Google search error: {e}")
        return None

    if not url:
        return None

    print(f"      🌐 Found ZmyHome URL: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # ปรับปรุง Logic การหาตาม DOM ที่ผู้ใช้ระบุ: 
            # <li class="col-3 info-project__item">
            #   <span class="small">ปีที่สร้างเสร็จ</span>
            #   ...
            #   <strong class="label">2557 (12 ปี)</strong>
            
            # ค้นหา Span ที่มีคำว่า 'ปีที่สร้างเสร็จ' (แบบยืดหยุ่นเรื่องช่องว่าง)
            target_span = soup.find('span', string=lambda t: t and 'ปีที่สร้างเสร็จ' in t)
            
            if target_span:
                # ลองหาใน parent <li>
                parent_li = target_span.find_parent('li')
                if parent_li:
                    strong_tag = parent_li.find('strong', class_='label')
                    if strong_tag:
                        text = strong_tag.get_text(strip=True)
                        print(f"      📄 Found match via DOM: '{text}'")
                        match = re.search(r'(\d{4})', text)
                        if match:
                            return match.group(1)
            
            # --- Fallback: ถ้าหาตามโครงสร้างตรงๆ ไม่เจอ ให้กวาดหาตัวเลข 4 หลักหลังคำว่า 'สร้างเสร็จปี' ทั้งหน้า ---
            all_text = soup.get_text()
            match = re.search(r'สร้างเสร็จปี\s*(\d{4})', all_text)
            if match:
                print(f"      📄 Found match via Fallback Regex: '{match.group(1)}'")
                return match.group(1)
    except Exception as e:
        print(f"      [!] Error scraping {url}: {e}")
        
    return None

def main():
    fs = FirestoreService()
    print("🚀 เริ่มสแกนคิวงานจาก 'Leads' ทั้งหมด เพื่อหาปีที่สร้างเสร็จจาก ZmyHome (เฉพาะตัวที่ยังไม่มี)...")
    
    lead_docs = fs.db.collection("Leads").get()
    count_updated = 0
    
    for lead_doc in lead_docs:
        prop_id = lead_doc.id # Document ID (อาจไม่ใช่ property_id จาก agent api แต่เราอ้างอิง doc นี้ได้เลย)
        lead_ref = lead_doc.reference
        lead_data = lead_doc.to_dict()

        # ข้ามเฉพาะอันที่ 'มีค่าเป็นตัวเลขแล้ว' (ถ้าเป็น None คือหาจาก LivingInsider/ZmyHome ไม่เจอ ให้ลองใหม่)
        if lead_data.get("built_year") is not None:
            continue
            
        # ดึงชื่อโครงการจาก Leads
        project_name = lead_data.get("sheet_ชื่อโครงการ")
        
        # Fallback to evaluation data
        if not project_name or str(project_name).strip().lower() in ["none", "null", "", "-", "ไม่ระบุ"]:
            eval_data = lead_data.get("evaluation", {})
            if isinstance(eval_data, dict):
                project_name = eval_data.get("project_name")
                
        if not project_name or str(project_name).strip().lower() in ["none", "null", "", "-", "ไม่ระบุ"]:
            # ไม่ต้องปริ้นท์ขยะเยอะ
            lead_ref.update({"built_year": None})
            continue
            
        print(f"🏢 Document ID: {prop_id} | Project: {project_name}")
        # ลองดึงข้อมูล โดยมีการจัดการ Error 429 (Too Many Requests)
        try:
            year_str = scrape_zmyhome_year(project_name)
            
            if year_str:
                year_int = int(year_str)
                print(f"   🎉 สำเร็จ! พบปีที่สร้างปี: {year_int} -> บันทึกลง Leads")
                lead_ref.update({
                    "built_year": year_int
                })
                count_updated += 1
            else:
                print(f"   ❌ ไม่พบปีที่สร้างเสร็จใน ZmyHome")
                lead_ref.update({
                    "built_year": None
                })
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "Too Many Requests" in err_msg:
                print(f"   ⚠️ โดน Google บล็อกชั่วคราว (Error 429)! หยุดพัก 60 วินาที...")
                time.sleep(60)
            else:
                print(f"   ❌ เกิดข้อผิดพลาดอื่น: {e}")
                
        # สุ่มพัก 5 - 15 วินาที เพื่อให้เหมือนคนกดค้นหา
        sleep_time = random.randint(5, 15)
        print(f"   ⏳ รอ {sleep_time} วินาทีก่อนทำรายการถัดไป...")
        time.sleep(sleep_time)

    print(f"✅ ทำงานเสร็จสิ้น: อัปเดตข้อมูล ZmyHome ใน Leads สำเร็จทั้งหมด {count_updated} รายการ")

if __name__ == "__main__":
    main()
