import os
import requests
from urllib.parse import quote

class GeocodingService:
    def __init__(self):
        self.api_key = os.getenv('GOOGLE_API_KEY')

    def get_coordinates(self, address):
        """
        Geocode an address to get latitude and longitude.
        """
        if not self.api_key or not address or address == "-":
            return None, None
            
        print(f"🌍 Geocoding address: {address}")
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(address)}&key={self.api_key}"
        
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if data['status'] == 'OK':
                loc = data['results'][0]['geometry']['location']
                return loc['lat'], loc['lng']
            else:
                print(f"Geocoding API returned status: {data['status']}")
                return None, None
        except Exception as e:
            print(f"Error during geocoding: {e}")
            return None, None
