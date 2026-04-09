import os
import sys
import time

project_root = os.path.abspath(os.curdir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

# ⚙️ ตั้งค่าคอลเลกชันที่ต้องการดึงข้อมูล (เปลี่ยนเป็น 'ARNON_properties' ได้ที่นี่)
SOURCE_COLLECTION = "Launch_Properties"

def get_specs_from_leads(fs, api_id):
    """
    ดึงข้อมูล specifications จาก Leads collection โดย match api_property_id
    คืนค่า dict หรือ {} ถ้าไม่เจอ
    """
    import re
    def extract_number(text):
        if not text: return ""
        nums = re.findall(r'\d+', str(text))
        return nums[0] if nums else ""

    try:
        # ค้นหาด้วย api_property_id (เก็บเป็น string หรือ int ก็รองรับ)
        results = fs.db.collection("Leads").where("api_property_id", "==", str(api_id)).limit(1).get()
        
        if not results:
            results = fs.db.collection("Leads").where("api_property_id", "==", int(api_id)).limit(1).get()

        if results:
            lead_data = results[0].to_dict()
            evaluation = lead_data.get("evaluation", {})
            if not isinstance(evaluation, dict):
                evaluation = {}
            
            # --- ดึงข้อมูล Bedroom ---
            beds = str(evaluation.get("bedrooms", "") or lead_data.get("bedrooms", "") or lead_data.get("sheet_Bedroom", ""))
            if not beds:
                # Fallback: แกะจาก sheet_Unit Type
                unit_type = str(lead_data.get("sheet_Unit Type", "")).lower()
                # เพิ่ม BR เข้าไปใน pattern
                if any(x in unit_type for x in ['bed', 'br', 'ห้องนอน', 'นอน']):
                    # พยายามหาตัวเลขที่อยู่หน้าคำว่า 'นอน', 'bed', หรือ 'br'
                    match = re.search(r'(\d+)\s*(?:bed|br|ห้องนอน|นอน)', unit_type)
                    if match:
                        beds = match.group(1)
                    else:
                        beds = extract_number(unit_type)
                
                # ถ้าเจอคำระบุว่าเป็นสตูดิโอ หรือไม่ระบุ ให้เป็น 0
                if any(x in unit_type for x in ['studio', 'สตูดิโอ', 'ไม่ระบุ']):
                    beds = "0"

            # --- ดึงข้อมูล Bathroom ---
            baths = str(evaluation.get("bathrooms", "") or lead_data.get("bathrooms", "") or lead_data.get("sheet_Bathroom", ""))
            if not baths:
                # ลองแกะจาก Unit Type (รองรับ 1 น้ำ, 3BT, 1 Bath)
                unit_type = str(lead_data.get("sheet_Unit Type", "")).lower()
                if any(x in unit_type for x in ['bath', 'bt', 'ห้องน้ำ', 'น้ำ']):
                    # ค้นหาตัวเลขที่อยู่หน้าคำว่า bath/bt/ห้องน้ำ/น้ำ
                    match = re.search(r'(\d+)\s*(?:bath|bt|ห้องน้ำ|น้ำ)', unit_type)
                    if match:
                        baths = match.group(1)

            # --- ดึงข้อมูล Floors ---
            floors = str(
                (evaluation.get("specifications", {}) or {}).get("floors", "")
                or evaluation.get("floor", "")
                or lead_data.get("sheet_ชั้น", "")
                or lead_data.get("sheet_Floor", "")
            )
            
            return {
                "bedrooms": beds,
                "bathrooms": baths,
                "floors": extract_number(floors) if floors else ""
            }
    except Exception as e:
        print(f"      [!] ไม่สามารถดึงจาก Leads: {e}")
    return {}


def update_agent_colors_and_style():
    print("==================================================")
    print("🎨 เริ่มต้นอัปเดตเฉพาะ Color และ Style ไปยัง Agent API")
    print("Endpoint: /api/agent/properties/{property_id}/update")
    print("==================================================")

    fs = FirestoreService()
    api = APIService()

    if not api.authenticate():
        print("❌ Login Agent API ล้มเหลว! ยกเลิกการอัปเดต")
        return

    # ดึงเฉพาะรายการที่ผ่านการวิเคราะห์สีแล้วจากระบบ
    # และยังไม่ได้สั่งอัปเดต (ป้องกันการยิงซ้ำ)
    print(f"📦 กำลังโหลดข้อมูลจาก '{SOURCE_COLLECTION}'...")
    all_docs = fs.db.collection(SOURCE_COLLECTION).where("analyzed", "==", True).stream()
    
    targets = []
    for doc in all_docs:
        data = doc.to_dict()
        api_id = data.get("api_property_id") or doc.id
        # เช็ค flag เพื่อไม่ให้อัปเดตซ้ำซ้อน (ถ้ามีแล้ว)
        if not data.get("uploaded_agent_color"):
             targets.append({
                 "doc_id": doc.id,
                 "api_id": str(api_id),
                 "house_color": data.get("house_color"),
                 "style": data.get("architect_style") or data.get("interior_style") or "Other",
                 # ดึง specs จาก SOURCE_COLLECTION ก่อน
                 "bedrooms": str(data.get("bedrooms", "") or ""),
                 "bathrooms": str(data.get("bathrooms", "") or ""),
                 "floors": str(data.get("floors", "") or ""),
             })

    print(f"🔥 พบรายการที่ต้องอัปเดต: {len(targets)} รายการ")
    
    success_count = 0
    fail_count = 0

    for idx, item in enumerate(targets, 1):
        doc_id = item["doc_id"]
        api_id = item["api_id"]
        h_color = item["house_color"]
        style_val = item["style"]

        if not h_color:
            print(f"[{idx}/{len(targets)}] ⏭️ ข้าม ID: {api_id} (ยังไม่มีข้อมูล house_color)")
            continue

        # ถ้าใน SOURCE_COLLECTION ไม่มี bedrooms/bathrooms/floors ให้ดึงจาก Leads
        bedrooms = item.get("bedrooms", "")
        bathrooms = item.get("bathrooms", "")
        floors = item.get("floors", "")

        if not bedrooms and not bathrooms and not floors:
            print(f"   🔍 ดึง specs จาก Leads สำหรับ API ID {api_id}...")
            lead_specs = get_specs_from_leads(fs, api_id)
            bedrooms = lead_specs.get("bedrooms", "")
            bathrooms = lead_specs.get("bathrooms", "")
            floors = lead_specs.get("floors", "")

        print(f"[{idx}/{len(targets)}] 🔄 ID: {api_id} | Color: {h_color} | Style: {style_val} | Beds: {bedrooms} | Baths: {bathrooms} | Floors: {floors}")

        # สร้าง specifications dict (ใส่เฉพาะ field ที่มีข้อมูลจริง)
        specs = {"style": style_val}
        if floors:   specs["floors"] = floors
        if bedrooms: specs["bedrooms"] = bedrooms
        if bathrooms: specs["bathrooms"] = bathrooms

        payload = {
            "house_color": h_color,
            "specifications": specs
        }

        # ยิงอัปเดตเข้า Agent API
        if api.update_property(api_id, payload):
            success_count += 1
            # อัปเดต Flag ใน Firestore ว่ายิงขึ้น Agent API แล้ว
            fs.db.collection(SOURCE_COLLECTION).document(doc_id).update({
                "uploaded_agent_color": True
            })
        else:
            fail_count += 1

        # หน่วงเวลา 2 วินาทีเพื่อไม่ให้ Server ปลายทางรับภาระหนักเกินไป
        time.sleep(2.0)

    print("\n" + "=" * 50)
    print(f"🏁 สรุปผลการอัปเดต -> สำเร็จ: {success_count} | ล้มเหลว: {fail_count}")
    print("=" * 50)

if __name__ == "__main__":
    update_agent_colors_and_style()
