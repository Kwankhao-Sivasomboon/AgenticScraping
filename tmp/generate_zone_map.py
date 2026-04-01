import os
import sys
import json
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

# Setup Root Path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

from src.services.maps_service import get_location_details

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
    print(f"🔍 Fetching unique zones from {collection_name}...")
    
    docs = db.collection(collection_name).stream()
    unique_zones = set()
    
    for doc in docs:
        data = doc.to_dict()
        zone = data.get('sheet_โซน')
        if zone and zone != "-" and zone != "None":
            unique_zones.add(zone)
            
    print(f"✅ Found {len(unique_zones)} unique zones: {unique_zones}")
    
    zone_locations = []
    for zone in sorted(list(unique_zones)):
        # Search for the zone in Thailand
        # Add 'กรุงเทพ' or 'Thailand' to help Google Maps
        search_query = f"{zone}, กรุงเทพ" if "กรุงเทพ" not in zone else zone
        loc = get_location_details(search_query)
        
        if loc and loc.get('latitude'):
            zone_locations.append({
                "zone": zone,
                "lat": float(loc['latitude']),
                "lng": float(loc['longitude']),
                "address": loc.get('address', '')
            })
            print(f"📍 {zone}: {loc['latitude']}, {loc['longitude']}")
        else:
            print(f"⚠️ Could not find location for zone: {zone}")

    # Generate HTML with Leaflet
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Property Zones Map</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
        #map {{ height: 100vh; width: 100%; }}
        .info-box {{
            position: absolute;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 1000;
            background: rgba(255, 255, 255, 0.9);
            padding: 10px 20px;
            border-radius: 25px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            border: 2px solid #007bff;
        }}
    </style>
</head>
<body>
    <div class="info-box">
        <b>🗺️ แผนที่พิกัด 36 โซน (จาก Firestore Leads)</b>
    </div>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([13.7563, 100.5018], 11);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '&copy; OpenStreetMap contributors'
        }}).addTo(map);

        var zones = {json.dumps(zone_locations, ensure_ascii=False)};
        
        zones.forEach(function(z) {{
            L.marker([z.lat, z.lng])
                .addTo(map)
                .bindPopup("<b>โซน: " + z.zone + "</b><br>" + z.address);
        }});
    </script>
</body>
</html>
"""

    with open("tmp/zone_map.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✨ Map generated at tmp/zone_map.html with {len(zone_locations)} markers.")

if __name__ == "__main__":
    main()
