import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService

def run_delete_legacy():
    print("🔥 Authenticating Firestore...")
    firestore = FirestoreService()
    if not firestore.db:
        print("❌ เชื่อมตัวกับ Firestore ไม่สำเร็จ")
        return

    print("🔍 กำลังค้นหาข้อมูลที่เป็น status: legacy_import ...")
    
    # Query for all documents where status == 'legacy_import'
    query = firestore.db.collection(firestore.collection_name).where("status", "==", "legacy_import")
    docs = query.stream()
    
    docs_to_delete = list(docs)
    total_docs = len(docs_to_delete)
    
    if total_docs == 0:
        print("ℹ️ ไม่พบข้อมูล legacy_import ในระบบ (เป็น 0)")
        return
        
    print(f"⚠️ พบข้อมูล legacy_import ทั้งหมด {total_docs} รายการ")
    
    confirm = input("💬 ยืนยันที่จะลบข้อมูลเหล่านี้ทั้งหมดหรือไม่? (y/n): ").strip().lower()
    if confirm != 'y':
        print("ยกเลิกการลบ!")
        return
        
    print("🗑️ กำลังเริ่มลบข้อมูล (พร้อม sub-collections)...")
    
    batch = firestore.db.batch()
    deleted_count = 0
    batch_count = 0
    
    for doc in docs_to_delete:
        doc_ref = doc.reference
        
        # ลบ Sub-collection (Analysis_Results) ถ้ามี
        sub_docs = doc_ref.collection("Analysis_Results").stream()
        for sub in sub_docs:
            batch.delete(sub.reference)
            batch_count += 1
            
        # ลบ Main Document
        batch.delete(doc_ref)
        batch_count += 1
        deleted_count += 1
        
        # Firestore batch limit is 500 operations
        if batch_count >= 400:
            batch.commit()
            batch = firestore.db.batch()
            batch_count = 0
            print(f"   ...ลบไปแล้ว {deleted_count} รายการ")
            
    # Commit whatever is left in the batch
    if batch_count > 0:
        batch.commit()
        
    print(f"\n✅ ลบข้อมูล legacy_import เสร็จสิ้นทั้งหมด {deleted_count} รายการ!")

if __name__ == "__main__":
    run_delete_legacy()
