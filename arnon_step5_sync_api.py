import os
import json
import time
import requests
from dotenv import load_dotenv

# Use Gemini for translation if needed
try:
    from google import genai
except ImportError:
    genai = None

# Add root folder to sys path to import FirestoreService
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.services.firestore_service import FirestoreService

load_dotenv()
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost")
STAFF_TOKEN = os.getenv("STAFF_TOKEN", "") # Use token from environment or config
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")

def translate_name(name, lang="th"):
    """Translate property name to EN or TH using Gemini"""
    if not genai: return name
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return name
    
    try:
        client = genai.Client(api_key=api_key)
        target = "Thai" if lang == "th" else "English"
        prompt = f"Property name: '{name}'. Give ONLY the {target} name used for properties. No quotes, no extra text. If it is already in {target}, return it as is."
        resp = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        return resp.text.strip()
    except:
        return name

def is_english(text):
    return any(c.isascii() and c.isalpha() for c in text)

def safe_float(val):
    try: return float(val)
    except: return None

TEST_MODE = True # ปรับเป็น False เมื่อพร้อมยิง API ของจริง

def main():
    print("🚀 Starting Step 5: Sync API for Condo/House Projects & Developers")
    
    fs = FirestoreService()
    if not fs.db:
        print("❌ Cannot connect to Firestore.")
        return
        
    print("⏳ Fetching documents from Firestore 'Leads' collection...")
    # Using raw Firestore query to pull all leads
    docs = fs.db.collection("Leads").get()
    
    developer_groups = {}
    
    for doc in docs:
        data = doc.to_dict()
        dev_name = data.get("zmyh_developer", "").strip() or "Unknown Developer"
        prj_name = data.get("sheet_ชื่อโครงการ", "").strip()
        
        if not prj_name:
            # Fallback
            eval_data = data.get("evaluation", {})
            if isinstance(eval_data, dict):
                prj_name = eval_data.get("project_name", "").strip()
                
        if not prj_name: continue
        
        if dev_name not in developer_groups:
            developer_groups[dev_name] = {}
            
        if prj_name not in developer_groups[dev_name]:
            developer_groups[dev_name][prj_name] = []
            
        developer_groups[dev_name][prj_name].append(data)
        
    print(f"📊 Found {len(developer_groups)} developers.")
    
    if TEST_MODE:
        print("\n--- 🧪 TEST MODE: Grouping Output Preview ---\n")
        total_projects = 0
        html_out = "<html><body style='font-family: sans-serif; padding: 20px;'><h1>Step 5 Grouping Report</h1>"
        
        for dev_name, projects in developer_groups.items():
            print(f"🏢 Developer: {dev_name}")
            html_out += f"<div style='margin-bottom: 20px; border-left: 5px solid #007bff; padding-left: 15px;'><h3>🏢 {dev_name}</h3><ul>"
            for prj_name, leads_list in projects.items():
                print(f"   ├─ 📌 Project: {prj_name} ({len(leads_list)} leads)")
                html_out += f"<li>📌 <b>{prj_name}</b> ({len(leads_list)} leads)</li>"
                total_projects += 1
            print("   └─────────────────────────────────────")
            html_out += "</ul></div>"
            
        print(f"\n✅ Total grouped Developers: {len(developer_groups)}")
        print(f"✅ Total grouped Projects: {total_projects}")
        
        html_out += f"<hr><h3>Summary</h3><p>Total Developers: {len(developer_groups)}</p><p>Total Projects: {total_projects}</p></body></html>"
        with open("step5_grouping_report.html", "w", encoding="utf-8") as f:
            f.write(html_out)
            
        print(f"\n📂 Exported report to: step5_grouping_report.html")
        print("⚠️ Running in TEST_MODE. APIs were NOT called. Set TEST_MODE = False to execute actual logic.")
        return
    
    # Process each grouped developer
    for dev_name, projects in developer_groups.items():
        print(f"\n🏢 Developer: {dev_name}")
        
        # 1. Translate Developer Name if necessary
        dev_name_th = dev_name
        dev_name_en = dev_name
        if is_english(dev_name):
            dev_name_th = translate_name(dev_name, "th")
        else:
            dev_name_en = translate_name(dev_name, "en")
            
        # 2. Create Developer via Agent API (POST /api/agent/developers)
        dev_payload = {
            "name_en": dev_name_en,
            "name_th": dev_name_th,
            "is_active": True
        }
        print(f"   -> Creating Developer: {dev_name_en} / {dev_name_th}")
        
        dev_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AGENT_TOKEN}"
        }
        
        developer_id = None
        # Mocking API Call since it depends on exact server state
        try:
            resp = requests.post(f"{API_BASE_URL}/api/agent/developers", json=dev_payload, headers=dev_headers)
            if resp.status_code in [200, 201]:
                dr = resp.json()
                if dr.get("data") and dr["data"].get("id"):
                    developer_id = dr["data"]["id"]
                elif "id" in dr:
                    developer_id = dr["id"]
                print(f"      ✅ Developer created/found, ID: {developer_id}")
            else:
                print(f"      ⚠️ Failed to create developer: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"      ❌ API Error: {e}")
        
        if not developer_id:
            developer_id = 1 # Fallback for now so the script can proceed
            
        # Process each project under this developer
        for prj_name, leads_list in projects.items():
            print(f"   📌 Project: {prj_name} ({len(leads_list)} leads)")
            
            # Translate Project Name
            prj_name_th = prj_name
            prj_name_en = prj_name
            if is_english(prj_name):
                prj_name_th = translate_name(prj_name, "th")
            else:
                prj_name_en = translate_name(prj_name, "en")
                
            print(f"      🌐 Translated: {prj_name_en} / {prj_name_th}")
            
            # Aggregate specs from leads (Take the first one that has data)
            built_year = None
            total_units = None
            floors = None
            parking = None
            launch_price = None
            
            for lead in leads_list:
                if lead.get("zmyh_built_year"): built_year = lead.get("zmyh_built_year")
                if lead.get("zmyh_total_units"): total_units = lead.get("zmyh_total_units")
                if lead.get("zmyh_max_floors"): floors = lead.get("zmyh_max_floors")
                if lead.get("zmyh_parking"): parking = lead.get("zmyh_parking")
                if lead.get("zmyh_launch_price"): launch_price = lead.get("zmyh_launch_price")
                
            built_date = None
            if built_year:
                try: built_date = f"{int(built_year)}-01-01"
                except: pass
                
            prices = [safe_float(re.sub(r'[^0-9.]', '', str(lp))) for lp in [launch_price] if lp] if launch_price else []
            clean_price = str(prices[0]) if prices else "0"
            
            # Clean floors
            clean_floors = "".join(filter(str.isdigit, str(floors))) if floors else "0"
            clean_units = "".join(filter(str.isdigit, str(total_units))) if total_units else "0"
            
            # 3. Create Condo Project (POST /api/staff/condo-projects)
            staff_headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {STAFF_TOKEN}"
            }
            
            # Multipart Form-Data setup
            form_data = {
                "developer_id": (None, str(developer_id)),
                "name_en": (None, prj_name_en),
                "name_th": (None, prj_name_th),
                "is_active": (None, "1"),
            }
            
            if built_date: form_data["built_date"] = (None, built_date)
            # if clean_price != "0": form_data["launch_price"] = (None, clean_price)
            if clean_units != "0": form_data["total_units"] = (None, clean_units)
            if clean_floors != "0": form_data["total_floors"] = (None, clean_floors)
            
            specs_json = json.dumps({"floors": clean_floors})
            form_data["specifications_json"] = (None, specs_json)
            
            try:
                # print("      🚀 Creating Project...")
                # resp = requests.post(f"{API_BASE_URL}/api/staff/condo-projects", files=form_data, headers=staff_headers)
                # if resp.status_code in [200, 201]:
                #     print(f"      ✅ Project created successfully.")
                # else:
                #     print(f"      ⚠️ Failed to create project: {resp.status_code} - {resp.text}")
                pass
            except Exception as e:
                print(f"      ❌ API Error: {e}")
                
            time.sleep(1) # Rate limit protection

    print("\n🎉 Step 5 Sync Complete!")

if __name__ == "__main__":
    main()
