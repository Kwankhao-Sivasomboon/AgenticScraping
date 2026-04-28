import os
import time
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService

load_dotenv()

# --- FINAL CONSTANTS ---
SYSTEM_COLOR_MAP = {
    "Green": "Green", "Brown": "Brown", "Red": "Red", "Dark Yellow": "Yellow",
    "Orange": "Orange", "Purple": "Pink", "Pink": "Pink",
    "Light Yellow": "Cream", "Yellowish Brown": "Cream", "Light Brown": "Cream",
    "White": "White", "Gray": "Gray", "Blue": "Blue", "Black": "Black"
}
SYSTEM_THAI_MAP = {
    "Black": "ดำ", "Blue": "น้ำเงิน", "Brown": "น้ำตาล", "Cream": "ครีม",
    "Gold": "ทอง", "Gray": "เทา", "Green": "เขียว", "Light Gray": "เทาอ่อน",
    "Orange": "ส้ม", "Pink": "ชมพู", "Red": "แดง", "Silver": "เงิน",
    "White": "ขาว", "Yellow": "เหลือง"
}
ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]

def fix_colors():
    fs = FirestoreService()
    print("🚀 Starting Color Recalculation (Ceiling Fix 0.2 + Cream Mapping)...")
    
    docs = fs.db.collection("area_color").where("true_color_analyzed", "==", True).get()
    print(f"📦 Found {len(docs)} analyzed properties to fix.")
    
    count = 0
    for doc in docs:
        prop_id = doc.id
        data = doc.to_dict()
        
        try:
            struct = data.get("structural_colors", {})
            breakdown = data.get("room_element_breakdown", {})
            
            def get_val(obj, key, idx):
                try:
                    # Handle both list and dict-like structural_colors
                    target = obj.get(key, [0]*14)
                    return target[idx]
                except: return 0

            # 1. Calculate Room Composition (with Ceiling Fix 0.2)
            room_comp = []
            for i in range(14):
                val = (
                    (get_val(struct, 'wall', i) * breakdown.get('wall', 0) / 100 * 2.0) + # 🔥 ผนังคูณ 2 (เน้นสีทาบ้าน)
                    (get_val(struct, 'floor', i) * breakdown.get('floor', 0) / 100) +
                    (get_val(struct, 'ceiling', i) * breakdown.get('ceiling', 0) / 100 * 0.2) + 
                    (get_val(struct, 'door', i) * breakdown.get('door', 0) / 100)
                )
                room_comp.append(val)
                
            # 2. Combine with Furniture
            room_w = data.get("area_weight", {}).get("room", 100) / 100
            furn_w = data.get("area_weight", {}).get("furniture", 0) / 100
            furn_comp = data.get("furniture_color_composition", [0]*14)
            
            combined = []
            for i in range(14):
                c_val = (room_comp[i] * room_w) + (furn_comp[i] * furn_w)
                combined.append(c_val)
                
            # 3. Map to System Colors
            system_scores = {c: 0.0 for c in set(SYSTEM_COLOR_MAP.values())}
            for i in range(14):
                ai_color = ENGLISH_COLORS[i]
                sys_color = SYSTEM_COLOR_MAP[ai_color]
                system_scores[sys_color] += combined[i]
                
            # 4. Sort and Get House Colors
            sorted_scores = sorted(system_scores.items(), key=lambda x: x[1], reverse=True)
            house_color = sorted_scores[0][0]
            house_color_thai = SYSTEM_THAI_MAP.get(house_color, "ไม่ระบุ")
            
            house_color2 = sorted_scores[1][0] if len(sorted_scores) > 1 and sorted_scores[1][1] > 0 else None
            house_color2_thai = SYSTEM_THAI_MAP.get(house_color2) if house_color2 else None
            
            # 5. Update Firestore
            fs.db.collection("area_color").document(prop_id).update({
                "house_color": house_color,
                "house_color_thai": house_color_thai,
                "house_color2": house_color2,
                "house_color2_thai": house_color2_thai,
                "system_color_scores": system_scores,
                "room_color_composition": [round(x) for x in room_comp] # Update overall room comp
            })
            
            count += 1
            if count % 50 == 0:
                print(f"✅ Fixed {count} properties...")
                
        except Exception as e:
            print(f"❌ Error fixing ID {prop_id}: {e}")

    print(f"🏁 FINISHED! Total properties updated: {count}")

if __name__ == "__main__":
    fix_colors()
