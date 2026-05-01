import os
from datetime import datetime
from dotenv import load_dotenv
from src.services.firestore_service import FirestoreService

load_dotenv()

# 14 สีดิบ ไม่มี Mapping
ENGLISH_COLORS = [
    "Green", "Brown", "Red", "Dark Yellow", "Orange", "Purple", "Pink",
    "Light Yellow", "Yellowish Brown", "Light Brown", "White", "Gray", "Blue", "Black"
]

def get_dominant_color(room_list, furn_list, room_w, furn_w):
    """คำนวณสีเด่นจาก room และ furniture โดยไม่มีการ Map สี"""
    def pad_list(lst):
        if not lst: return [0] * 14
        if len(lst) < 14: return list(lst) + [0] * (14 - len(lst))
        return lst[:14]

    room_list = pad_list(room_list)
    furn_list = pad_list(furn_list)

    scores = {}
    for i in range(14):
        score = (room_list[i] * room_w) + (furn_list[i] * furn_w)
        color_name = ENGLISH_COLORS[i]
        scores[color_name] = scores.get(color_name, 0) + score

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    dominant = sorted_scores[0][0] if sorted_scores else "Unknown"
    dominant2 = sorted_scores[1][0] if len(sorted_scores) > 1 and sorted_scores[1][1] > 0 else None
    return dominant, dominant2, sorted_scores

def generate_comparison_report():
    fs = FirestoreService()
    print("🔍 Generating Color Comparison Report (No Mapping, 3-way compare)...")

    # ดึงทุก property ที่มีใน Launch_Properties
    lp_docs = fs.db.collection("Launch_Properties").get()

    comparisons = []
    global_old_stats = {}    # 50/50
    global_new_stats = {}    # area_weight from area_color
    total = 0

    for lp_doc in lp_docs:
        prop_id = lp_doc.id
        lp_data = lp_doc.to_dict()

        # ดึงข้อมูลดิบจาก Launch_Properties
        room_list = lp_data.get("room_color", [0] * 14)
        furn_list = lp_data.get("element_color", [0] * 14)

        if not any(room_list): continue  # ถ้าไม่มีข้อมูลข้าม

        # ดึง area_weight จาก area_color
        ac_doc = fs.db.collection("area_color").document(prop_id).get()
        if ac_doc.exists:
            ac_data = ac_doc.to_dict()
            area_weight = ac_data.get("area_weight", {})
            ac_room_w = area_weight.get("room", 100) / 100
            ac_furn_w = area_weight.get("furniture", 0) / 100
        else:
            ac_room_w = 1.0
            ac_furn_w = 0.0
            ac_data = {}

        total += 1

        # --- OLD COLOR: room_color + element_color จาก Launch_Properties × 50/50 ---
        old_color, _, old_scores = get_dominant_color(room_list, furn_list, 0.5, 0.5)

        # --- NEW COLOR: room_color + element_color จาก Launch_Properties × area_weight จาก area_color ---
        new_color, new_color2, new_scores = get_dominant_color(room_list, furn_list, ac_room_w, ac_furn_w)

        global_old_stats[old_color] = global_old_stats.get(old_color, 0) + 1
        global_new_stats[new_color] = global_new_stats.get(new_color, 0) + 1

        # ดึงรูปจาก Launch_Properties
        images = lp_data.get("images", [])[:3]

        comparisons.append({
            "id": prop_id,
            "old_color": old_color,       # 50/50
            "new_color": new_color,        # area_weight
            "new_color2": new_color2,
            "old_scores": old_scores[:4],
            "new_scores": new_scores[:4],
            "room_w": ac_room_w * 100,
            "furn_w": ac_furn_w * 100,
            "images": images,
            "changed": old_color != new_color
        })

    # เรียงตาม area_weight ที่สุดขั้ว (ห่างจาก 50/50 มากที่สุดก่อน)
    comparisons.sort(key=lambda x: abs(x["room_w"] - 50), reverse=True)
    display_list = comparisons

    # Summary
    all_colors = sorted(set(list(global_old_stats.keys()) + list(global_new_stats.keys())))
    summary_data = []
    for color in all_colors:
        old_p = (global_old_stats.get(color, 0) / total * 100) if total > 0 else 0
        new_p = (global_new_stats.get(color, 0) / total * 100) if total > 0 else 0
        trend = new_p - old_p
        summary_data.append({
            "color": color, "old": f"{old_p:.1f}%", "new": f"{new_p:.1f}%",
            "trend": f"{trend:+.1f}%", "trend_val": trend
        })
    summary_data.sort(key=lambda x: x["trend_val"])

    changed_count = sum(1 for c in comparisons if c["changed"])

    html_report = f"""
    <html>
    <head>
        <title>Color Comparison Report</title>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; padding: 20px; background: #f4f4f9; color: #333; }}
            h1 {{ color: #2c3e50; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 30px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #2c3e50; color: white; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .trend-up {{ color: green; font-weight: bold; }}
            .trend-down {{ color: red; font-weight: bold; }}
            .img-container img {{ width: 180px; height: 135px; object-fit: cover; margin-right: 5px; border-radius: 6px; }}
            .card {{ border: 1px solid #ddd; padding: 15px; margin-bottom: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
            .changed {{ border-left: 4px solid #e74c3c; }}
            .same {{ border-left: 4px solid #2ecc71; }}
            .badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.9em; font-weight: bold; background: #ecf0f1; }}
            .color-old {{ background: #ffeeba; }}
            .color-new {{ background: #d4edda; }}
        </style>
    </head>
    <body>
        <h1>📊 Color Comparison Report (No Mapping)</h1>
        <p><b>Total Properties:</b> {total} | <b>Color Changed (Old 50/50 ≠ New area_weight):</b> {changed_count}</p>
        <p><b>Old Color</b> = Launch_Properties (room_color × 50% + element_color × 50%)<br>
           <b>New Color</b> = Launch_Properties × area_weight จาก area_color</p>
        <h2>📈 Overall Shift Summary</h2>
        <table>
            <tr><th>Color</th><th>Old % (50/50)</th><th>New % (area_weight)</th><th>Trend</th></tr>
    """

    for row in summary_data:
        trend_class = "trend-up" if row["trend_val"] > 0 else "trend-down" if row["trend_val"] < 0 else ""
        html_report += f'<tr><td>{row["color"]}</td><td>{row["old"]}</td><td>{row["new"]}</td><td class="{trend_class}">{row["trend"]}</td></tr>'

    html_report += "</table>"
    html_report += f"<h2>🔍 All {len(display_list)} Properties (Changed First)</h2>"

    for c in display_list:
        img_tags = ""
        for img in c["images"]:
            # พยายามหา URL ที่น่าจะใช้งานได้ที่สุด
            url = img.get("validated_url") or img.get("url") or ""
            
            if url:
                if not url.startswith("http"):
                    # ถ้าเป็น path สั้น ให้ต่อกับ domain หลัก
                    url = "https://app.yourhome.co.th/" + url.lstrip("/")
                
                img_tags += f'<img src="{url}" loading="lazy" onerror="this.style.display=\'none\'">'

        card_class = "changed" if c["changed"] else "same"
        html_report += f"""
        <div class="card {card_class}">
            <h3>Property ID: {c['id']} &nbsp;<a href="https://yourhome.co.th/property/{c['id']}" target="_blank" style="font-size:0.8em; color:#3498db;">🔗 View on yourhome.co.th</a></h3>
            <p>
                <b>Old Color (50/50):</b> <span class="badge color-old">{c['old_color']}</span>
                &nbsp;&nbsp;
                <b>New Color 1 (area_weight):</b> <span class="badge color-new">{c['new_color']}</span>
                &nbsp;&nbsp;
                <b>New Color 2:</b> <span class="badge">{c['new_color2'] if c['new_color2'] else '-'}</span>
            </p>
            <p>
                <b>area_weight:</b> Room {c['room_w']:.1f}% | Furniture {c['furn_w']:.1f}%
            </p>
            <p>
                <b>Old Scores (50/50):</b> {c['old_scores']}<br>
                <b>New Scores (area_weight):</b> {c['new_scores']}
            </p>
            <div class="img-container">{img_tags}</div>
        </div>
        """

    html_report += "</body></html>"

    with open("final_color_report.html", "w", encoding="utf-8") as f:
        f.write(html_report)
    print(f"✅ Final report generated: final_color_report.html ({total} properties, {changed_count} changed)")

if __name__ == "__main__":
    generate_comparison_report()
