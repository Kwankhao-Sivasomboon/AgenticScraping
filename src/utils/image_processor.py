import io
import requests
from PIL import Image

class ImageService:
    def __init__(self):
        # We can initialize AI clients here if needed
        pass

    def check_watermark_cheap(self, image_buffer):
        """
        เช็คด้วยโมเดลราคาถูกก่อน (Placeholder for lightweight classifier or heuristics)
        Returns True if watermark is detected, False otherwise.
        """
        # TODO: Implement an actual lightweight check (e.g., using Gemini vision, 
        # a small ONNX model, or basic OpenCV heuristics).
        # For now, we assume no watermark to proceed with upload safely,
        # or implement a dummy random check.
        return False
        
    def remove_watermark_expensive(self, image_buffer):
        """
        ลบลายน้ำด้วย model ราคาแพง (บน RAM) (e.g., LaMa, Stable Diffusion Inpainting, OpenCV inpaint)
        Returns the cleaned image buffer.
        """
        print("🪄 Executing Advanced Watermark Removal logic...")
        # TODO: Connect to your actual LaMa/OpenCV pipeline here.
        # It must treat image_buffer (BytesIO) as input and return a new BytesIO.
        # For now, returning the original buffer.
        image_buffer.seek(0)
        return image_buffer

    def process_images(self, image_urls):
        """
        Downloads images, applies watermark removal workflow, and returns memory buffers.
        Returns a list of tuples: [("image_1.jpg", BytesIO_object), ...]
        """
        processed_files = []
        for i, url in enumerate(image_urls):
            try:
                print(f"⬇️ Downloading image {i+1} into RAM...")
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    img_buffer = io.BytesIO(response.content)
                    
                    # 1. เช็คด้วยโมเดลราคาถูกก่อน
                    has_watermark = self.check_watermark_cheap(img_buffer)
                    if has_watermark:
                        print(f"⚠️ Watermark detected on image {i+1}. Removing...")
                        # 2. ลบลายน้ำด้วย model ราคาแพง (บน RAM)
                        img_buffer = self.remove_watermark_expensive(img_buffer)
                    else:
                        print(f"✅ Image {i+1} is clean.")
                        
                    # Standardize format to JPEG
                    img = Image.open(img_buffer)
                    if img.mode not in ("RGB"):
                        img = img.convert("RGB")
                    
                    final_buffer = io.BytesIO()
                    img.save(final_buffer, format="JPEG", quality=90)
                    final_buffer.seek(0)
                    
                    processed_files.append((f"photo_{i+1}.jpg", final_buffer))
            except Exception as e:
                print(f"❌ Failed to process image {url}: {e}")
                
        return processed_files
