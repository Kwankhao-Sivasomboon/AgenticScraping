import os
import sys
import time

project_root = os.path.abspath(os.curdir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.services.api_service import APIService

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
    print("📦 กำลังโหลดข้อมูลจาก Firestore...")
    all_docs = fs.db.collection(fs.collection_name).where("analyzed", "==", True).stream()
    
    targets = []
    for doc in all_docs:
        data = doc.to_dict()
        api_id = data.get("api_property_id") or doc.id
        # เช็ค flag เพื่อไม่ให้อัปเดตซ้ำซ้อน (ถ้ามีแล้ว)
        if not data.get("uploaded_agent_color"):
             targets.append({
                 "doc_id": doc.id,
                 "api_id": api_id,
                 "house_color": data.get("house_color"),
                 "style": data.get("architect_style") or data.get("interior_style") or "Other"
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

        print(f"[{idx}/{len(targets)}] 🔄 อัปเดต ID: {api_id} | Color: {h_color} | Style: {style_val}")

        # Payload ที่ส่งมีเฉพาะที่บอสต้องการเท่านั้น (Patch Update)
        payload = {
            "house_color": h_color,
            "specifications": {
                "style": style_val
            }
        }

        # ยิงอัปเดตเข้า Agent API
        if api.update_property(api_id, payload):
            success_count += 1
            # อัปเดต Flag ใน Firestore ว่ายิงขึ้น Agent API แล้ว
            fs.db.collection(fs.collection_name).document(doc_id).update({
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
