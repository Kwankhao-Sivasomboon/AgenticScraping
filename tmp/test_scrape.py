import requests
from bs4 import BeautifulSoup
import re

url = "https://zmyhome.com/project/Noble-Reflex-943" # Just an example
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print(f"Testing URL: {url}")
try:
    r = requests.get(url, headers=headers, timeout=15)
    print(f"Status Code: {r.status_code}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Method 1: Original logic
        spans = soup.find_all('span', class_='small', string=re.compile(r'ปีที่สร้างเสร็จ'))
        print(f"Found spans with 'ปีที่สร้างเสร็จ': {len(spans)}")
        for span in spans:
            parent_li = span.find_parent('li')
            if parent_li:
                strong_tag = parent_li.find('strong', class_='label')
                if strong_tag:
                    print(f"Method 1 Match: {strong_tag.get_text(strip=True)}")

        # Method 2: More generic search
        for item in soup.find_all(['span', 'div', 'li']):
            text = item.get_text()
            if "ปีที่สร้างเสร็จ" in text:
                print(f"Generic Match found in {item.name}: {text[:50]}...")
                # Look for digits
                match = re.search(r'\b(25\d{2}|20\d{2})\b', text)
                if match:
                    print(f"Method 2 Match (Year): {match.group(1)}")
                    
except Exception as e:
    print(f"Error: {e}")
