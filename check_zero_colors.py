
import os
import sys

# Setup Root Path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService

def check_zero_colors():
    fs = FirestoreService()
    print("--- Scanning Firestore for properties with zero-color matrices ---")
    
    docs = fs.db.collection(fs.collection_name).stream()
    
    zero_element_count = 0
    zero_room_count = 0
    total_scanned = 0
    found_ids = []

    for doc in docs:
        total_scanned += 1
        data = doc.to_dict()
        pid = data.get("api_property_id", doc.id)
        
        element_color = data.get("element_color")
        room_color = data.get("room_color")

        # Check if all zeros
        is_zero_element = False
        if isinstance(element_color, list) and len(element_color) > 0:
            if all(v == 0 for v in element_color):
                is_zero_element = True
                zero_element_count += 1

        is_zero_room = False
        if isinstance(room_color, list) and len(room_color) > 0:
            if all(v == 0 for v in room_color):
                is_zero_room = True
                zero_room_count += 1
                
        if is_zero_element or is_zero_room:
            found_ids.append({
                "id": pid,
                "zero_element": is_zero_element,
                "zero_room": is_zero_room
            })
            if len(found_ids) <= 30: # Show first 30
                print(f"   [Alert] ID: {pid} | Element Zero: {is_zero_element} | Room Zero: {is_zero_room}")

    print("\n" + "="*40)
    print(f"Summary Scan (Total {total_scanned} records):")
    print(f"   - Zero Element Color Count: {zero_element_count}")
    print(f"   - Zero Room Color Count: {zero_room_count}")
    print("="*40)
    
    if found_ids:
        print(f"💡 รายการเหล่านี้ต้องการการวิเคราะห์ใหม่ (Force Analyze)")

if __name__ == "__main__":
    check_zero_colors()
