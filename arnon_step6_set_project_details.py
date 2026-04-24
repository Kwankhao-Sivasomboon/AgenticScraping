import os
import time
import requests
import json
from dotenv import load_dotenv
from src.services.api_service import APIService
from src.services.firestore_service import FirestoreService

load_dotenv()

# ==========================================================
# ⚙️ Configuration
# ==========================================================
API_BASE_URL = os.getenv("AGENT_API_BASE_URL")
COLLECTION = "Leads"
TARGET_DEVELOPER = None
TEST_LIMIT = None
RESET_FLAGS = False # 🚩 ตั้งเป็น True เพื่อล้างค่า details_linked เก่าทั้งหมดกลับเป็น False

def main():
    print(f"🚀 Starting Step 6: Linking Properties (Syncing with Postman Style)")
    fs = FirestoreService()
    leads_ref = fs.db.collection(COLLECTION)

    # 🔄 0. Reset Flags if requested
    if RESET_FLAGS:
        print("🧹 Resetting all 'details_linked' flags to False...")
        to_reset = leads_ref.where("details_linked", "==", True).stream()
        reset_count = 0
        for doc in to_reset:
            doc.reference.update({"details_linked": False})
            reset_count += 1
        print(f"✅ Reset {reset_count} flags.")

    api = APIService()
    current_account_is_arnon = None 

    def get_auth_header(use_arnon=False):
        nonlocal current_account_is_arnon
        if current_account_is_arnon != use_arnon:
            api.token = None
            current_account_is_arnon = use_arnon
            
        if api.authenticate(use_arnon=use_arnon):
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api.token}",
                "X-Requested-With": "XMLHttpRequest"
            }
        return None

    # 🔥 ดึง Leads
    print("⏳ Fetching leads...")
    query = leads_ref.where("project_synced", "==", True).stream()
    
    total_processed = 0
    success_count = 0
    
    for doc in query:
        if TEST_LIMIT and total_processed >= TEST_LIMIT: break

        data = doc.to_dict()
        doc_id = doc.id
        dev_name = data.get("zmyh_developer") or data.get("developer") or ""
        
        if TARGET_DEVELOPER and TARGET_DEVELOPER.lower() not in dev_name.lower(): continue
        
        property_id = data.get("api_property_id")
        project_id = data.get("project_id")
        project_type = data.get("project_type", "condo")
        
        if not property_id or not project_id: continue
        if data.get("details_linked"): continue

        print(f"\n🔗 [{dev_name}] Linking Property {property_id} -> Project {project_id} ({project_type})")
        
        is_condo = "condo" in str(project_type).lower()
        endpoint = f"/api/agent/properties/{property_id}/condo-details" if is_condo else f"/api/agent/properties/{property_id}/house-details"
        payload = {"condo_project_id" if is_condo else "house_project_id": int(project_id)}
        url = f"{API_BASE_URL}{endpoint}"

        # 1. ลองด้วยบัญชีหลักก่อน
        headers = get_auth_header(use_arnon=False)
        if not headers:
            print("   ❌ Auth Failed. Sleeping 20s...")
            time.sleep(20)
            continue

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            
            # 🛡️ Handle 429
            if resp.status_code == 429:
                print("   🛑 Too Many Requests (429)! Sleeping 30s...")
                time.sleep(30)
                continue

            # 🛡️ Handle 403 - Fallback to Arnon
            if resp.status_code == 403:
                print(f"   ⚠️ 403 Forbidden for primary account. Trying Arnon fallback...")
                time.sleep(4.0) # ⏳ เพิ่มดีเลย์เล็กน้อยก่อนสลับบัญชี
                arnon_headers = get_auth_header(use_arnon=True)
                if arnon_headers:
                    resp = requests.post(url, json=payload, headers=arnon_headers, timeout=20)
                
            if resp.status_code in [200, 201]:
                print(f"   ✅ Linked Successfully!")
                leads_ref.document(doc_id).update({"details_linked": True})
                success_count += 1
            else:
                print(f"   ⚠️ Failed: {resp.status_code}")
                print(f"   📍 Target URL: {url}")
                print(f"   📦 Body: {json.dumps(payload)}")
                err_text = resp.text[:300] + "..." if len(resp.text) > 300 else resp.text
                print(f"   📥 Response: {err_text}")
                
        except Exception as e:
            print(f"   ❌ API Error: {e}")
            
        total_processed += 1
        time.sleep(3.0)

    print(f"\n🎉 Task Complete! Success: {success_count}")

if __name__ == "__main__":
    main()
