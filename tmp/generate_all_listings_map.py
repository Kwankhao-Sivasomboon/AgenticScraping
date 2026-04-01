import os
import sys
import json
import random
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

# Setup Root Path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

def generate_color(seed):
    """สร้างสีที่คงที่ตามชื่อโซน"""
    random.seed(seed)
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

def main():
    # Initialize Firestore
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE') or 'agentic-scraping-pptd-f7bc092f86f3.json'
    database_id = 'livinginsider-scraping'
    
    if os.path.exists(credentials_file):
        cred = service_account.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(project=cred.project_id, credentials=cred, database=database_id)
    else:
        print("❌ Credentials file not found.")
        return

    collection_name = 'Leads'
    print(f"🔍 Fetching ALL listings with coordinates from {collection_name}...")
    
    docs = db.collection(collection_name).stream()
    listings = []
    zones_found = set()
    
    for doc in docs:
        data = doc.to_dict()
        lat = data.get('latitude')
        lng = data.get('longitude')
        zone = data.get('sheet_โซน', 'ไม่ระบุ')
        
        # กรองเฉพาะที่มีพิกัด
        try:
            if lat and lng and str(lat) != "0" and str(lng) != "0":
                listings.append({
                    "id": doc.id,
                    "title": data.get('title', 'Unknown Property'),
                    "lat": float(lat),
                    "lng": float(lng),
                    "zone": zone,
                    "price": data.get('sheet_ราคาขาย') or data.get('sheet_ราคาเช่า') or "-"
                })
                zones_found.add(zone)
        except:
            continue
            
    print(f"✅ Loaded {len(listings)} listings across {len(zones_found)} zones.")

    # สร้าง Map ของสีประจำโซน
    zone_colors = {zone: generate_color(zone) for zone in sorted(list(zones_found))}

    # Generate HTML with Leaflet and Sidebar
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Interactive Property Map - All Listings</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Leaflet -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <style>
        body {{ margin: 0; padding: 0; display: flex; height: 100vh; font-family: sans-serif; }}
        #map {{ flex-grow: 1; }}
        #sidebar {{
            width: 300px;
            background: #f8f9fa;
            border-left: 1px solid #ddd;
            overflow-y: auto;
            padding: 20px;
            box-shadow: -2px 0 5px rgba(0,0,0,0.1);
        }}
        h2 {{ font-size: 1.2rem; margin-top: 0; color: #333; }}
        .zone-item {{
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            font-size: 0.9rem;
            cursor: pointer;
            padding: 4px;
            border-radius: 4px;
        }}
        .zone-item:hover {{ background: #eee; }}
        .color-dot {{
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
            border: 1px solid #999;
        }}
        .stats {{ font-size: 0.8rem; color: #666; margin-bottom: 20px; }}
        .custom-pin {{
            border-radius: 50%;
            border: 2px solid white;
            box-shadow: 0 0 4px rgba(0,0,0,0.5);
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <div id="sidebar">
        <h2>📍 เลือกโซนเพื่อแสดงหมุด</h2>
        <div class="stats">เลือกโซนทางขวาเพื่อปักหมุดบนแผนที่</div>
        <div id="zone-list">
            <div class="zone-item">
                <input type="checkbox" id="check-all" onclick="toggleAll(this.checked)"> <b>เลือก/ยกเลิก ทั้งหมด</b>
            </div>
            <hr>
            <!-- Zone items injected here -->
        </div>
    </div>

    <script>
        var map = L.map('map').setView([13.7563, 100.5018], 11);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; OpenStreetMap contributors'
        }}).addTo(map);

        var listings = {json.dumps(listings, ensure_ascii=False)};
        var zoneColors = {json.dumps(zone_colors, ensure_ascii=False)};
        var activeZones = new Set(); // เริ่มต้นด้วย Set ว่างเปล่า

        // Create Layer Group for markers
        var markerLayer = L.layerGroup().addTo(map);

        function getIcon(color) {{
            const size = 12;
            return L.divIcon({{
                className: 'custom-pin',
                html: `<div style="background-color: ${{color}}; width: ${{size}}px; height: ${{size}}px; border-radius: 50%; border: 1px solid white;"></div>`,
                iconSize: [size, size],
                iconAnchor: [size/2, size/2]
            }});
        }}

        function renderMarkers() {{
            markerLayer.clearLayers();
            listings.forEach(function(item) {{
                if (activeZones.has(item.zone)) {{
                    var color = zoneColors[item.zone];
                    var marker = L.marker([item.lat, item.lng], {{
                        icon: getIcon(color)
                    }}).bindPopup(`<b>${{item.title}}</b><br>โซน: ${{item.zone}}<br>ราคา: ${{item.price}}`);
                    
                    marker.addTo(markerLayer);
                }}
            }});
        }}

        function updateZoneList() {{
            var listDiv = document.getElementById('zone-list');
            Object.keys(zoneColors).sort().forEach(zone => {{
                var item = document.createElement('div');
                item.className = 'zone-item';
                var color = zoneColors[zone];
                
                item.innerHTML = `
                    <input type="checkbox" class="zone-check" data-zone="${{zone}}">
                    <div class="color-dot" style="background: ${{color}}"></div>
                    <span>${{zone}}</span>
                `;
                
                item.querySelector('input').onclick = function(e) {{
                    if (this.checked) activeZones.add(this.dataset.zone);
                    else activeZones.delete(this.dataset.zone);
                    renderMarkers();
                }};
                
                listDiv.appendChild(item);
            }});
        }}

        function toggleAll(isChecked) {{
            activeZones.clear();
            var checks = document.querySelectorAll('.zone-check');
            checks.forEach(c => {{
                c.checked = isChecked;
                if (isChecked) activeZones.add(c.dataset.zone);
            }});
            renderMarkers();
        }}

        updateZoneList();
        renderMarkers();

    </script>
</body>
</html>
"""

    with open("tmp/all_listings_map.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✨ Advanced Map generated at tmp/all_listings_map.html")

if __name__ == "__main__":
    main()
