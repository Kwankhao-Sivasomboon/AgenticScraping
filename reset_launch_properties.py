import os
from src.services.firestore_service import FirestoreService

def reset_menu():
    fs = FirestoreService()
    
    print("==================================================")
    print("🧹 Firestore Reset Utility (Stream Mode)")
    print("==================================================")
    print("1. Reset ALL (analyzed=False, uploaded=False) -> สำหรับเริ่มวิเคราะห์สีใหม่ (Step 2/3)")
    print("2. Reset Agent Sync Flag (uploaded_agent_color=False) -> สำหรับเริ่มอัปเดตสี/สไตล์ใหม่ (Agent API)")
    print("==================================================")
    
    choice = input("เลือกโหมดที่ต้องการ (1/2): ").strip()
    
    # ถามชื่อคอลเลกชันเพื่อความยืดหยุ่น (เผื่อบอสสลับไปถังใหม่)
    collection_name = input("ระบุชื่อ Collection (ค่าเริ่มต้น 'Launch_Properties'): ").strip() or "Launch_Properties"
    
    print(f"📦 กำลังประมวลผลข้อมูลจาก '{collection_name}' ผ่าน Stream...")
    
    # ใช้ .stream() แทน .get() เพื่อรองรับปริมาณข้อมูลที่มากกว่า 500 รายการอย่างเสถียร
    docs_stream = fs.db.collection(collection_name).stream()
    
    batch = fs.db.batch()
    count = 0
    found_any = False
    
    for doc in docs_stream:
        found_any = True
        if choice == "1":
            batch.update(doc.reference, {
                "analyzed": False,
                "uploaded": False 
            })
        elif choice == "2":
            batch.update(doc.reference, {
                "uploaded_agent_color": False
            })
        else:
            print("❌ เลือกโหมดไม่ถูกต้อง")
            return
            
        count += 1
        
        # Firestore batch limit is 500
        if count % 500 == 0:
            batch.commit()
            batch = fs.db.batch()
            print(f"   ✅ Reset สำเร็จแล้ว {count} รายการ...")

    if not found_any:
        print(f"❌ ไม่พบเอกสารใน {collection_name}")
        return

    # Commit สุดท้ายสำหรับเศษที่เหลือ
    batch.commit()
    print(f"✨ เรียบร้อย! Reset ทั้งหมด {count} รายการ ใน collection '{collection_name}' สำเร็จ")

if __name__ == "__main__":
    reset_menu()
