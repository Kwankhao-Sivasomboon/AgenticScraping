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
        คุณเป็น AI ผู้ช่วยวิเคราะห์ข้อมูลอสังหาริมทรัพย์ระดับมืออาชีพหน้าที่ของคุณคือการสกัดข้อมูลและแปลงให้อยู่ในรูปแบบ JSON อย่างเคร่งครัด
        
        โปรดสกัดข้อมูลต่อไปนี้ (หากไม่พบข้อมูลในช่องใดให้คืนค่าเป็น null):
        1. "listing_date": วันที่ลงประกาศหรืออัปเดตล่าสุดที่พบในหน้าเว็บ (เช่น 'เมื่อวาน', '10 ต.ค. 2566')
        2. "customer_name": ชื่อเจ้าของประกาศ **ให้ค้นหาจากใน "เนื้อหาประกาศ (Description)" ก่อน (มักจะอยู่ใกล้ๆ กับเบอร์โทรศัพท์)** หากในเนื้อหาประกาศไม่มีชื่อเจ้าของระบุไว้ จึงค่อยนำข้อมูลจาก `Extracted Owner Name` มาใช้ ห้ามใช้ชื่อบริษัทเช่น YourHome.Agent เด็ดขาด
        3. "project_name": ชื่อโครงการ สรุปให้กระชับและเป็นมาตรฐาน
        4. "price_sell": ราคาขาย เก็บเป็นตัวเลข
        5. "price_rent": ราคาเช่า (ต่อเดือน) เก็บเป็นตัวเลข
        6. "phone_number": เบอร์โทรศัพท์ที่พบ **ต้องเป็นเบอร์มือถือที่ถูกต้อง (ขึ้นต้นด้วย 06, 08, 09 และมีตัวเลข 10 ตัว)**
        7. "line_id": ไอดีไลน์ หรือ เบอร์/ตัวเลขอื่นๆ (เช่น 653620536) ที่พบจากการกดไอคอนหรือในข้อความ แต่**ไม่ใช่รหัสเบอร์มือถือ 10 หลัก** ให้นำมาใส่ที่ช่องนี้แทน
        8. "floor": จำนวนชั้น/ชั้นที่ตั้ง ให้ดึงข้อมูลมาเป็น **ตัวเลขเดี่ยวๆ** เท่านั้น (เช่น 3, 5, 12) หากเป็นช่วงระบุให้คาดเดาตัวเลขใดตัวเลขหนึ่งมา ห้ามมีตัวหนังสือเด็ดขาด
        9. "type": ระบุว่าเป็นการ "ขาย" หรือ "เช่า" หรือ "ขายและเช่า"
        10. "building_size": ขนาดพื้นที่ใช้สอยของห้องหรืออาคาร หน่วยเป็น ตร.ม. (ตัวเลขเท่านั้น เช่น 35) ถ้าไม่พบให้คืน null
        10b. "land_size": ขนาดที่ดิน หน่วยเป็น ตร.ว. (ตัวเลขเท่านั้น เช่น 50) ถ้าไม่พบให้คืน null
        11. "bed_bath": จำนวนห้องนอน และห้องน้ำ (เช่น "3 นอน 2 น้ำ") สำหรับใส่ใน Google Sheets
        12. "house_number": บ้านเลขที่ หรือเลขที่ห้อง
        13. "address": ที่อยู่หรือถนน หากเป็นโครงการระบุชื่อโครงการและซอย
        14. "city": จังหวัด หรือเขต (เช่น "Bangkok", "Nonthaburi", "กรุงเทพมหานคร")
        15. "postal_code": รหัสไปรษณีย์
        16. "latitude": ละติจูด (หากมีตัวเลขพิกัด) รบกวนคืนค่าเป็นทศนิยม
        17. "longitude": ลองจิจูด (หากมีตัวเลขพิกัด) รบกวนคืนค่าเป็นทศนิยม
        18. "specifications": เป็นอ็อบเจ็กต์ JSON ได้แก่: "floors", "bedrooms", "bathrooms", "parking_spaces" (ค่าเป็นตัวเลขหรือ null)
        19. "specification_values": เป็นอ็อบเจ็กต์ JSON ได้แก่: "common_facilities" (Array string), "furniture_items" (Array string)
        20. "direction": ทิศของระเบียงหรือหน้าบ้าน (เช่น "เหนือ", "ใต้", "ตะวันออก", "ตะวันตก", "ตะวันออกเฉียงเหนือ", "ตะวันออกเฉียงใต้", "ตะวันตกเฉียงเหนือ", "ตะวันตกเฉียงใต้")
        21. "furnishing": สภาพเฟอร์นิเจอร์ เลือกจาก: "โนเฟอร์", "เฟอร์นิเจอร์บางส่วน", "เฟอร์นิเจอร์ครบ" (หากไม่ทราบให้ใส่ null)

        ข้อมูลชื่อเจ้าของที่บอทขูดมาได้เบื้องต้น (Extracted Owner Name):
        {parsed_data.get('owner_name', 'null')}
        
        ข้อมูลเบอร์โทรเสริม (Extracted Phone):
        {parsed_data.get('extracted_phone', 'null')}
        
        ข้อความดิบ (Raw Text Input):
        {parsed_data.get('raw_text', '')}
        
        ข้อมูลการติดต่อจากไอคอน (Contact Info From Icon):
        {parsed_data.get('contact_icon', 'null')}
        
        กรุณาส่งคืนผลลัพธ์เป็น JSON Object ห้ามมี markdown ครอบ
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
            "listing_date": "-",
            "customer_name": "Error Parsing",
            "project_name": "-",
            "price_sell": "-",
            "price_rent": "-",
            "phone_number": "Error Parsing",
            "line_id": "-",
            "floor": "-",
            "type": "-",
            "size": "-",
            "bed_bath": "-",
            "house_number": "-",
            "address": "-",
            "city": "-",
            "postal_code": "-",
            "latitude": "-",
            "longitude": "-",
            "specifications": {},
            "specification_values": {},
            "direction": "ไม่ระบุทิศ"
        }
