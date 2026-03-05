import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class EvaluatorAgent:
    def __init__(self):
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is not set in environment variables.")
        
        # New genai client initialization
        self.client = genai.Client(api_key=api_key)
        # Using Gemini 2.5 Flash
        self.model_name = 'gemini-2.5-flash'
        
    def evaluate_listing(self, parsed_data):
        """
        Intelligence Phase: One-Shot Analysis using Gemini 2.5 Flash
        Receives raw_text and images, extracts details based on user requirements.
        """
        print(f"Evaluating listing ID: {parsed_data.get('listing_id', 'Unknown')}")
        
        prompt = f"""
        คุณเป็น AI ผู้ช่วยวิเคราะห์ข้อมูลอสังหาริมทรัพย์ระดับมืออาชีพหน้าที่ของคุณคือการสกัดข้อมูลจากข้อความดิบ (Raw Text) ที่เก็บมาจากหน้าเว็บไซต์ และแปลงให้อยู่ในรูปแบบ JSON อย่างเคร่งครัด
        
        โปรดสกัดข้อมูลต่อไปนี้:
        1. "customer_name": ชื่อผู้ลงประกาศ (Owner/Agent) ถ้าไม่พบให้ใส่ "Unknown"
        3. "price": ราคา (เช่า หรือ ขาย) เก็บเป็นตัวเลขหรือข้อความที่อ่านเข้าใจง่าย
        2. "phone_number": เบอร์โทรศัพท์ ถ้ามีหลายเบอร์คั่นด้วยคอมม่า 
           **เงื่อนไขสำคัญ**: ให้หาจาก "ข้อความดิบ" ก่อน (มักจะตามหลังคำว่า สนใจติดต่อ, โทร, 📞) เช่น "081~651~3612" ให้ลบสัญลักษณ์แปลงให้เป็นรูปแบบปกติ (081-651-3612) และถ้าเจอ "Line_URL" จาก "ข้อมูลการติดต่อจากไอคอน" ให้เติมต่อท้ายเสมอ (เช่น 081-123-4567, Line: https://...) ถ้าในข้อความ "ไม่มีเบอร์" ให้ใส่ "-" แล้วตามด้วย Line URL แทน
        4. "floor": ชั้นที่ตั้งของห้อง/บ้าน ถ้าไม่พบใส่ "-"
        5. "type": ระบุว่าเป็นการ "ขาย" หรือ "เช่า"
        6. "size": ขนาดพื้นที่ (เช่น 30 ตร.ม., 50 sq.w.)
        7. "bed_bath": จำนวนห้องนอน และห้องน้ำ (เช่น "1 นอน 1 น้ำ")
        8. "house_number": บ้านเลขที่ (ถ้ามีระบุไว้) ถ้าไม่พบใส่ "-"
        9. "lead_score": ให้คะแนนความสมบูรณ์ของข้อมูล 1-10 (ยิ่งมีชื่อ เบอร์โทร และรายละเอียดครบ ยิ่งได้คะแนนสูง)
        10. "images_url": นำ URL รูปภาพที่ให้ไปใส่คั่นด้วยคอมม่า
        
        ข้อความดิบ (Raw Text Input):
        {parsed_data.get('raw_text', '')}
        
        ข้อมูลการติดต่อจากไอคอน (Contact Info From Icon):
        {parsed_data.get('contact_icon', 'ไม่พบ')}
        
        Link รูปภาพ (Images URL Input):
        {', '.join(parsed_data.get('images', []))}
        
        กรุณาส่งคืนผลลัพธ์เป็น JSON Object ควบคุมรูปแบบให้สามารถใช้ json.loads() ใน Python ได้ทันที ห้ามมี markdown (เช่น ```json) ครอบ
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
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
