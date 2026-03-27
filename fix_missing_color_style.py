"""
fix_missing_color_style.py
==========================
สคริปต์สำหรับแก้ไข/เติมข้อมูลที่หายไป: `color` และ `interior_style` ใน Firestore

Logic:
  1. วนดึงทุก Document ใน Firestore
  2. ถ้า `interior_style` ว่าง → ดึงรูป 5 รูปแรกที่สินค้ามีใน Firestore ส่งให้ AI วิเคราะห์ใหม่ แล้วบันทึก
  3. ถ้า `color` ว่าง:
     a. ถ้ามี `room_color` อยู่ → หยิบ index ที่มีค่าสูงสุดมาแปลงเป็นชื่อสีภาษาไทย
     b. ถ้าไม่มี `room_color` แต่มีรูป → ส่ง AI วิเคราะห์ซ้ำเพื่อให้ได้ทั้ง color + room_color ใหม่

Usage:
  python fix_missing_color_style.py [start_api_id] [end_api_id]
  python fix_missing_color_style.py 1821 2524
"""

import os
import sys
import time

project_root = os.path.abspath(os.curdir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.services.firestore_service import FirestoreService
from src.room_analyzer.style_classifier import analyze_room_images, download_image

# แผนที่ index → ชื่อสีภาษาไทย (14 สีตาม Matrix)
COLOR_MATRIX_NAMES = [
    "สีเขียว",       # 0
    "สีน้ำตาล",      # 1
    "สีแดง",         # 2
    "สีเหลืองเข้ม",  # 3
    "สีส้ม",         # 4
    "สีม่วง",        # 5
    "สีชมพู",        # 6
    "สีเหลืองอ่อน",  # 7
    "สีเหลืองปนน้ำตาล", # 8
    "สีน้ำตาลอ่อน",  # 9
    "สีขาว",         # 10
    "สีเทา",         # 11
    "สีน้ำเงิน",     # 12
    "สีดำ",          # 13
]


def get_dominant_color_from_matrix(room_color: list) -> str:
    """หาสีที่มี % สูงสุดจาก room_color matrix และแปลงเป็นชื่อภาษาไทย"""
    if not room_color or len(room_color) < 14:
        return ""
    max_idx = room_color.index(max(room_color))
    return COLOR_MATRIX_NAMES[max_idx]


def fix_missing_data(start_id: int = None, end_id: int = None):
    fs = FirestoreService()

    print("=" * 50)
    print("🔧 Fix Missing color / interior_style")
    print(f"📍 ช่วง API ID: {start_id or 'ALL'} - {end_id or 'ALL'}")
    print("=" * 50)

    # ดึงข้อมูลทั้งหมดมาก่อน แล้ว filter ใน Python
    print("📦 กำลังโหลดข้อมูลจาก Firestore...")
    all_docs = list(fs.db.collection(fs.collection_name).stream())
    print(f"🔥 พบทั้งหมด {len(all_docs)} documents")

    targets = []
    for doc in all_docs:
        data = doc.to_dict()
        pid = data.get("api_property_id")

        # กรองช่วง ID
        if start_id or end_id:
            try:
                pid_int = int(pid)
                if start_id and pid_int < start_id:
                    continue
                if end_id and pid_int > end_id:
                    continue
            except (ValueError, TypeError):
                continue

        # เช็คว่าต้องแก้ไขอะไรบ้าง
        color_val = data.get("color", "")
        style_val = data.get("interior_style", "")
        room_color = data.get("room_color", [])
        images = data.get("images", [])

        need_style = not style_val or str(style_val).strip() in ["", "-", "None", "null"]
        need_color = not color_val or str(color_val).strip() in ["", "-", "None", "null"]

        if need_style or need_color:
            targets.append({
                "doc_id": doc.id,
                "api_id": pid,
                "data": data,
                "need_style": need_style,
                "need_color": need_color,
                "room_color": room_color,
                "images": images if isinstance(images, list) else [],
            })

    print(f"\n✅ พบ {len(targets)} รายการที่ต้องแก้ไข\n")

    fixed = 0
    skipped = 0

    for idx, item in enumerate(targets, 1):
        doc_id = item["doc_id"]
        api_id = item["api_id"]
        need_style = item["need_style"]
        need_color = item["need_color"]
        room_color = item["room_color"]
        images = item["images"]

        print(f"\n[{idx}/{len(targets)}] 📄 Doc: {doc_id} | API ID: {api_id}")
        print(f"   🔍 ต้องแก้: style={need_style}, color={need_color}")

        update_payload = {}

        # === กรณีที่ 1: ต้องการ color แต่มี room_color อยู่แล้ว ===
        if need_color and room_color and len(room_color) >= 14:
            dominant_color = get_dominant_color_from_matrix(room_color)
            if dominant_color:
                print(f"   🎨 คำนวณสีจาก room_color matrix → {dominant_color}")
                update_payload["color"] = dominant_color
                need_color = False  # แก้ได้แล้วโดยไม่ต้อง AI

        # === กรณีที่ 2: ยังต้อง AI (ต้องการ style หรือ color ที่ไม่มี room_color) ===
        if need_style or need_color:
            if not images:
                print(f"   ⏭️ ไม่มีรูปภาพใน Firestore → ข้ามไม่สามารถวิเคราะห์ AI ได้")
                skipped += 1
                continue

            # ส่งแค่ 5 รูปแรกเพื่อประหยัด Token
            sample_urls = images[:5]
            print(f"   🤖 ส่ง {len(sample_urls)} รูปให้ AI วิเคราะห์...")
            try:
                analysis = analyze_room_images(sample_urls)
                if analysis:
                    if need_style:
                        update_payload["interior_style"] = analysis.interior_style
                        print(f"   ✅ ได้ interior_style: {analysis.interior_style}")
                    if need_color:
                        update_payload["color"] = analysis.color
                        print(f"   ✅ ได้ color: {analysis.color}")
                        # ถ้าไม่มี room_color เลย ให้อัปเดตพร้อมกันเลย
                        if not room_color or len(room_color) < 14:
                            update_payload["room_color"] = analysis.room_color
                            update_payload["element_color"] = analysis.element_color
                            update_payload["element_furniture"] = [
                                ", ".join(items) if items else ""
                                for items in (analysis.element_furniture or [])
                            ]
                            print(f"   ✅ อัปเดต room_color matrix ด้วย")
                else:
                    print(f"   ❌ AI ไม่ได้คืนผล → ข้าม")
                    skipped += 1
                    continue
            except Exception as e:
                print(f"   ❌ AI Error: {e} → ข้าม")
                skipped += 1
                continue

            # หน่วงเวลาเล็กน้อยเพื่อไม่ให้ Gemini rate limit
            time.sleep(1)

        # === บันทึก Firestore ===
        if update_payload:
            fs.db.collection(fs.collection_name).document(doc_id).update(update_payload)
            print(f"   📝 บันทึกลง Firestore: {list(update_payload.keys())}")
            fixed += 1
        else:
            print(f"   ⏭️ ไม่มีอะไรต้องอัปเดต")
            skipped += 1

    print("\n" + "=" * 50)
    print(f"🏁 เสร็จสิ้น! แก้ไขแล้ว: {fixed} รายการ | ข้าม: {skipped} รายการ")
    print("=" * 50)


if __name__ == "__main__":
    start_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    end_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    fix_missing_data(start_id, end_id)
