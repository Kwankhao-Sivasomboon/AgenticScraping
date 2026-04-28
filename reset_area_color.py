from src.services.firestore_service import FirestoreService
from google.cloud import firestore

def reset_firestore():
    print("🔄 Starting Firestore reset...")
    fs = FirestoreService()
    docs = fs.db.collection('area_color').get()
    
    batch = fs.db.batch()
    count = 0
    total_count = 0
    
    for doc in docs:
        ref = fs.db.collection('area_color').document(doc.id)
        # ลบฟิลด์ทิ้งเพื่อให้กลับไปเป็นสถานะเหมือนยังไม่เคยรัน
        batch.update(ref, {
            'true_color_analyzed': firestore.DELETE_FIELD,
            'uploaded': firestore.DELETE_FIELD
        })
        count += 1
        total_count += 1
        
        # Commit ทีละ 400 รายการ (Firestore จำกัด batch ไม่เกิน 500)
        if count == 400:
            batch.commit()
            print(f"✅ Reset {total_count} documents...")
            batch = fs.db.batch()
            count = 0

    if count > 0:
        batch.commit()
        
    print(f"🎉 Successfully reset {total_count} properties in 'area_color'!")

if __name__ == "__main__":
    reset_firestore()
