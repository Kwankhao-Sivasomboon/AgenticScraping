import os
import io
import zipfile
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

class DriveService:
    def __init__(self):
        self.scopes = ['https://www.googleapis.com/auth/drive']
        self.credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
        
        try:
            self.credentials = Credentials.from_service_account_file(
                self.credentials_file, scopes=self.scopes
            )
            self.drive_service = build('drive', 'v3', credentials=self.credentials)
        except Exception as e:
            print(f"Error connecting to Google Drive: {e}")
            self.drive_service = None

    def create_zip_and_upload_to_drive(self, image_urls, listing_id):
        if not self.drive_service:
            print("Drive service not initialized. Can't upload.")
            return "-"
            
        if not image_urls:
            return "-"
            
        print(f"Creating ZIP file for {listing_id} with {len(image_urls)} images...")
        try:
            # 1. ดาวน์โหลดและรวมไฟล์ ZIP ใน Memory (ไม่ต้องบันทึกลง Disk)
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for i, url in enumerate(image_urls):
                    try:
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            zip_file.writestr(f"image_{i+1}.jpg", response.content)
                    except Exception as e:
                        print(f"Failed to download image {url}: {e}")
                        continue
                        
            zip_buffer.seek(0)
            
            # 2. อัปโหลดขึ้น Google Drive โดยใช้ service account ตัวเดิม
            print(f"Uploading ZIP to Google Drive for {listing_id}...")
            file_metadata = {'name': f'images_{listing_id}.zip', 'mimeType': 'application/zip'}
            
            drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            if drive_folder_id:
                file_metadata['parents'] = [drive_folder_id]
                
            media = MediaIoBaseUpload(zip_buffer, mimetype='application/zip', resumable=True)
            file = self.drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            
            # 3. ตั้งค่าสิทธิ์ให้ Anyone with link can view (ถ้าต้องการ)
            self.drive_service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()
            
            return file.get('webViewLink') # คืนค่าเป็นลิงก์ดาวน์โหลด
            
        except Exception as e:
            print(f"Error creating/uploading ZIP for {listing_id}: {e}")
            return "-"
