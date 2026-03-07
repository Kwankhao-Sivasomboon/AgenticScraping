import os
import io
import zipfile
import requests
from PIL import Image
from google.cloud import storage
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

class StorageService:
    def __init__(self):
        self.credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
        try:
            self.credentials = service_account.Credentials.from_service_account_file(self.credentials_file)
            self.client = storage.Client(credentials=self.credentials, project=self.credentials.project_id)
            
            # ดึงชื่อ Bucket จาก .env (รองรับทั้ง FIREBASE_FOLDER_PATH และ GCS_BUCKET_NAME)
            raw_bucket_path = os.getenv('FIREBASE_FOLDER_PATH') or os.getenv('GCS_BUCKET_NAME')
            
            if raw_bucket_path:
                # ถ้ามี gs:// นำหน้า ให้ตัดออกเอาแค่ชื่อ bucket
                self.bucket_name = raw_bucket_path.replace('gs://', '').strip().split('/')[0]
            else:
                # ค่าเริ่มต้นจะพยายามชี้ไปที่ bucket หลักของ Firebase
                self.bucket_name = f"{self.credentials.project_id}.appspot.com"
                
            print(f"📦 Using Firebase Bucket: {self.bucket_name}")
            self.bucket = self.client.bucket(self.bucket_name)
        except Exception as e:
            print(f"Error initializing Cloud Storage service: {e}")
            self.client = None

    def create_zip_and_upload(self, image_urls, listing_id):
        if not self.client:
            print("Storage service not initialized.")
            return "-"
            
        if not image_urls:
            return "-"
            
        print(f"Creating ZIP file (WebP encoded) for {listing_id} with {len(image_urls)} images...")
        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for i, url in enumerate(image_urls):
                    try:
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            # โหลดภาพด้วย Pillow และแปลงเป็น WebP
                            img = Image.open(io.BytesIO(response.content))
                            
                            # ปรับโหมดสีเพื่อป้องกัน Error (WebP รองรับ RGB และ RGBA)
                            if img.mode not in ("RGB", "RGBA"):
                                img = img.convert("RGB")
                            
                            webp_buffer = io.BytesIO()
                            # ย่อรูป Save เป็น WebP quality=85 เพื่อลดขนาดสุดๆ
                            img.save(webp_buffer, format="WEBP", quality=85)
                            
                            # เพิ่มลงใน ZIP ด้วยสกุล .webp
                            zip_file.writestr(f"image_{i+1}.webp", webp_buffer.getvalue())
                    except Exception as e:
                        print(f"Failed to download/convert image {url}: {e}")
                        continue
                        
            zip_buffer.seek(0)
            
            print(f"Uploading ZIP to Firebase/Cloud Storage for {listing_id}...")
            # เก็บไว้ในโฟลเดอร์ listings/<ID> เพื่อความเป็นระเบียบ
            blob_name = f"listings/{listing_id}/images_{listing_id}.zip"
            blob = self.bucket.blob(blob_name)
            
            blob.upload_from_file(zip_buffer, content_type='application/zip')
            
            # เปิดให้ลิงก์กดโหลดได้โดยไม่ต้องล็อกอิน (Public)
            try:
                blob.make_public()
            except Exception as e:
                print(f"Note: Could not make blob public (Bucket rights might be restricted): {e}")
                
            public_url = blob.public_url
            return public_url
            
        except Exception as e:
            print(f"Error creating/uploading ZIP for {listing_id}: {e}")
            return "-"
