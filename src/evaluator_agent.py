import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class EvaluatorAgent:
    def __init__(self):
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set in environment variables.")
        
        genai.configure(api_key=api_key)
        # Using Gemini 1.5 Flash - fast and supports multi-modal if needed later
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        
    def evaluate_listing(self, parsed_data):
        """
        Intelligence Phase: One-Shot Analysis using Gemini 1.5 Flash
        Receives raw_text and images, extracts details based on user requirements.
        """
        print(f"Evaluating listing ID: {parsed_data.get('listing_id', 'Unknown')}")
        
        prompt = f"""
        คุณเป็น AI ผู้ช่วยวิเคราะห์ข้อมูลอสังหาริมทรัพย์ระดับมืออาชีพหน้าที่ของคุณคือการสกัดข้อมูลจากข้อความดิบ (Raw Text) ที่เก็บมาจากหน้าเว็บไซต์ และแปลงให้อยู่ในรูปแบบ JSON อย่างเคร่งครัด
        
        โปรดสกัดข้อมูลต่อไปนี้:
        1. "customer_name": ชื่อผู้ลงประกาศ (Owner/Agent) ถ้าไม่พบให้ใส่ "Unknown"
        2. "phone_number": เบอร์โทรศัพท์ ถ้ามีหลายเบอร์คั่นด้วยคอมม่า ถ้าไม่พบใส่ "Unknown"
        3. "price": ราคา (เช่า หรือ ขาย) เก็บเป็นตัวเลขหรือข้อความที่อ่านเข้าใจง่าย
        4. "floor": ชั้นที่ตั้งของห้อง/บ้าน ถ้าไม่พบใส่ "-"
        5. "type": ระบุว่าเป็นการ "ขาย" หรือ "เช่า"
        6. "size": ขนาดพื้นที่ (เช่น 30 ตร.ม., 50 sq.w.)
        7. "bed_bath": จำนวนห้องนอน และห้องน้ำ (เช่น "1 นอน 1 น้ำ")
        8. "house_number": บ้านเลขที่ (ถ้ามีระบุไว้) ถ้าไม่พบใส่ "-"
        9. "lead_score": ให้คะแนนความสมบูรณ์ของข้อมูล 1-10 (ยิ่งมีชื่อ เบอร์โทร และรายละเอียดครบ ยิ่งได้คะแนนสูง)
        10. "images_url": นำ URL รูปภาพที่ให้ไปใส่คั่นด้วยคอมม่า
        
        ข้อความดิบ (Raw Text Input):
        {parsed_data.get('raw_text', '')}
        
        Link รูปภาพ (Images URL Input):
        {', '.join(parsed_data.get('images', []))}
        
        กรุณาส่งคืนผลลัพธ์เป็น JSON Object ควบคุมรูปแบบให้สามารถใช้ json.loads() ใน Python ได้ทันที ห้ามมี markdown (เช่น ```json) ครอบ
        """

        try:
            response = self.model.generate_content(prompt)
            clean_text = response.text.replace('```json', '').replace('```', '').strip()
            result = json.loads(clean_text)
            return result
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Gemini response: {e}")
            return self._get_fallback_dict()
        except Exception as e:
            print(f"Error during Gemini evaluation: {e}")
            return self._get_fallback_dict()

    def _get_fallback_dict(self):
        return {
            "customer_name": "Error Parsing",
            "phone_number": "Error Parsing",
            "price": "-",
            "floor": "-",
            "type": "-",
            "size": "-",
            "bed_bath": "-",
            "house_number": "-",
            "lead_score": 0,
            "images_url": "-"
        }
