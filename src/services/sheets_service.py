import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

class SheetsService:
    def __init__(self):
        self.scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        self.credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
        self.sheet_url = os.getenv('GOOGLE_SHEET_URL')
        
        if not self.sheet_url:
            raise ValueError("GOOGLE_SHEET_URL is not set in environment variables.")
        
        try:
            self.credentials = Credentials.from_service_account_file(
                self.credentials_file, scopes=self.scopes
            )
            self.client = gspread.authorize(self.credentials)
            # ระบุชื่อ Sheet: LivingInsider
            self.sheet = self.client.open_by_url(self.sheet_url).worksheet('LivingInsider')
        except Exception as e:
            print(f"Error connecting to Google Sheets: {e}")
            self.sheet = None

    def get_existing_listing_ids(self):
        """
        Reads the Google Sheet and extracts all existing Listing IDs or URLs to memory 
        for deduplication. Assuming Listing ID is in column B (index 2) or URL in C.
        """
        if not self.sheet:
            return set()
            
        try:
            # Assuming row 1 is header
            # Adjust column index based on your actual sheet structure
            # Let's say Listing ID is in column B (2) and URL is in column C (3)
            # You can fetch all records and extract them
            records = self.sheet.get_all_records()
            existing_ids = set()
            for record in records:
                listing_id = str(record.get('Listing ID', '')).strip()
                url = str(record.get('URL', '')).strip()
                if listing_id:
                    existing_ids.add(listing_id)
                elif url:
                    existing_ids.add(url)
                    
            return existing_ids
        except Exception as e:
            print(f"Error reading existing records: {e}")
            return set()

    def append_data(self, data):
        """
        Appends a list of raw values to the next available row.
        `data` should be a list in the order of the sheet columns.
        E.g. [Date, ListingID, URL, Title, Price, Name, Phone, Requirements, LeadScore]
        """
        if not self.sheet:
            return False
            
        try:
            # ใช้ table_range='A:A' เพื่อบังคับให้ระบบหาบรรทัดว่างจากคอลัมน์แรก 
            # ป้องกันปัญหาข้อมูลไปต่อกันเป็นแนวนอนยาวๆ 
            self.sheet.append_row(
                data, 
                value_input_option='USER_ENTERED',
                table_range='A:A'
            )
            return True
        except Exception as e:
            print(f"Error appending data to Google Sheet: {e}")
            return False
