
import os
import sys
import datetime
import time

# Setup Root Path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

def direct_sync():
    # 🎯 รับ Parameter: ID เดี่ยว, 'all', 'resume <id>', หรือ 'start_id end_id'
    mode = "single"
    start_id = None
    end_id = None
    resume_id = None
    api_id_target = None
    
    if len(sys.argv) < 2:
        print("❌ Usage:")
        print("   python sync_color_matrices_to_api.py 346          (Single)")
        print("   python sync_color_matrices_to_api.py all          (All in Firestore)")
        print("   python sync_color_matrices_to_api.py resume 1821  (Resume from ID)")
        print("   python sync_color_matrices_to_api.py 1000 2000    (Range)")
        return
        
    arg1 = sys.argv[1].lower()
    if arg1 == "all":
        mode = "all"
    elif arg1 == "resume" and len(sys.argv) > 2:
        mode = "resume"
        resume_id = int(sys.argv[2])
    elif len(sys.argv) > 2:
        mode = "range"
        start_id = int(sys.argv[1])
        end_id = int(sys.argv[2])
    else:
        api_id_target = arg1
        
    api = APIService()
    # 🔐 Login Staff
    if not api.authenticate_staff():
        print("❌ Staff Auth Failed")
        return
        
    fs = FirestoreService()
    
    # 🔍 Fetch list of documents
    print(f"🔍 Fetching properties from Firestore (Mode: {mode})...")
    if mode == "single":
        query = fs.db.collection(fs.collection_name).where("api_property_id", "in", [int(api_id_target), str(api_id_target)]).limit(1).get()
        all_docs = list(query)
    else:
        # Load ALL documents
        all_docs_stream = list(fs.db.collection(fs.collection_name).stream())
        eligible_docs = []
        for d in all_docs_stream:
            pid = d.to_dict().get("api_property_id")
            if pid:
                try:
                    # 🎯 รองรับทั้ง '1333', 1333, '1333.0', 1333.0
                    val = float(pid)
                    eligible_docs.append(d)
                except (ValueError, TypeError):
                    continue
        
        # เรียงตาม ID จากน้อยไปมาก
        eligible_docs.sort(key=lambda x: int(x.to_dict().get("api_property_id")))
        
        if mode == "range":
            all_docs = [d for d in eligible_docs if start_id <= int(d.to_dict().get("api_property_id")) <= end_id]
        elif mode == "resume":
            all_docs = [d for d in eligible_docs if int(d.to_dict().get("api_property_id")) >= resume_id]
        else:
            all_docs = eligible_docs

    if not all_docs:
        print("❌ No properties found to sync.")
        return

    import random
    print(f"🔥 Found {len(all_docs)} properties to process...")
    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, doc in enumerate(all_docs, 1):
        data = doc.to_dict()
        api_id = data.get("api_property_id")
        
        room_color = data.get("room_color")
        element_color = data.get("element_color")
        element_furniture_raw = data.get("element_furniture", [])
        
        if not room_color or not element_color:
            skip_count += 1
            continue

        print(f"[{idx}/{len(all_docs)}] 📤 Syncing Property ID: {api_id}...")
        
        furniture_elements = []
        for i in range(14):
            item_list = []
            if i < len(element_furniture_raw):
                raw = element_furniture_raw[i]
                if isinstance(raw, list): item_list = raw
                elif isinstance(raw, str) and raw.strip():
                    item_list = [x.strip() for x in raw.split(",") if x.strip()]
            furniture_elements.append(item_list)

        payload = {
            "property_id": int(api_id),
            "analyzed_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "room_color": room_color,
            "furniture_color": element_color,
            "furniture_elements": furniture_elements
        }
        
        if api.submit_color_analysis(payload):
            success_count += 1
        else:
            fail_count += 1
            
        # --- เพิ่ม Delay เพื่อไม่ให้ Server แตก (ตามคำสั่งบอส 2-3 วิ) ---
        delay = random.uniform(2.0, 3.0)
        time.sleep(delay)

    print("\n" + "="*30)
    print(f"🏁 Sync Complete!")
    print(f"✅ Success: {success_count}")
    print(f"⏭️ Skip: {skip_count}")
    print(f"❌ Fail: {fail_count}")
    print("="*30)

    print("\n" + "="*30)
    print(f"🏁 Sync Complete!")
    print(f"✅ Success: {success_count}")
    print(f"⏭️ Skip: {skip_count}")
    print(f"❌ Fail: {fail_count}")
    print("="*30)

if __name__ == "__main__":
    direct_sync()
