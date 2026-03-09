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
        
        โปรดสกัดข้อมูลต่อไปนี้:
        1. "listing_date": วันที่ลงประกาศหรืออัปเดตล่าสุดที่พบในหน้าเว็บ (เช่น 'เมื่อวาน', '10 ต.ค. 2566') ถ้าไม่พบจริงๆ ให้ใส่ "-"
        2. "customer_name": ชื่อเจ้าของประกาศ **ให้ค้นหาจากใน "เนื้อหาประกาศ (Description)" ก่อน (มักจะอยู่ใกล้ๆ กับเบอร์โทรศัพท์)** หากในเนื้อหาประกาศไม่มีชื่อเจ้าของระบุไว้ จึงค่อยนำข้อมูลจาก `Extracted Owner Name` มาใช้ ห้ามใช้ชื่อบริษัทเช่น YourHome.Agent เด็ดขาด ถ้าหาไม่พบจริงๆ ให้ใส่ "-"
        3. "project_name": ชื่อโครงการ สรุปให้กระชับและเป็นมาตรฐาน ถ้าไม่พบให้ใส่ "-"
        4. "price_sell": ราคาขาย เก็บเป็นตัวเลขหรือข้อความที่อ่านง่าย (หากในรายละเอียดไม่มี ให้สังเกตจากคำว่า [ราคาที่สกัดจากระบบ]) ถ้าไม่พบใส่ "-"
        5. "price_rent": ราคาเช่า (ต่อเดือน) เก็บเป็นตัวเลขหรือข้อความที่อ่านง่าย (หากในรายละเอียดไม่มี ให้สังเกตจากคำว่า [ราคาที่สกัดจากระบบ]) ถ้าไม่พบใส่ "-"
        6. "phone_number": เบอร์โทรศัพท์ที่พบ **ต้องเป็นเบอร์มือถือที่ถูกต้อง (ขึ้นต้นด้วย 06, 08, 09 และมีตัวเลข 10 ตัว)** ถ้าในเนื้อหามีการใส่รหัสแปลกๆ (เช่น 653620536 หรือ qr code) ที่ไม่ใช่รูปแบบเบอร์ 10 หลัก *ห้ามนำมาใส่ที่นี่* เด็ดขาด ถ้าหาไม่พบเบอร์ที่ถูกต้องเลยให้ตอบ "-"
        7. "line_id": ไอดีไลน์ หรือ เบอร์/ตัวเลขอื่นๆ (เช่น 653620536) ที่พบจากการกดไอคอนหรือในข้อความ แต่**ไม่ใช่รหัสเบอร์มือถือ 10 หลัก** ให้นำมาใส่ที่ช่องนี้แทน ถ้าไม่พบใส่ "-"
        8. "floor": จำนวนชั้น/ชั้นที่ตั้ง **ให้ค้นหาจากใน "เนื้อหาประกาศ (Description)" ก่อนเป็นอันดับแรก** (เช่น "ชั้น 19", "อาคาร A ชั้น 1", "ชั้น 8") หากเป็นบ้านให้หาจำนวนชั้น (เช่น "2 ชั้น") หากในเนื้อหาประกาศไม่ระบุชั้นที่ชัดเจน จึงค่อยๆ พิจารณาจากข้อมูลที่สกัดมาจากระบบ (อาจเป็นช่วงเช่น 1-4) ถ้าไม่พบอะไรเลยให้ใส่ "-"
        9. "type": ระบุว่าเป็นการ "ขาย" หรือ "เช่า" หรือ "ขายและเช่า"
        10. "size": ขนาดพื้นที่ (เช่น 30 ตร.ม.)
        10. "bed_bath": จำนวนห้องนอน และห้องน้ำ (เช่น "1 นอน 1 น้ำ") สำหรับใส่ในช่อง Unit Type
        11. "house_number": บ้านเลขที่ หรือเลขที่ห้อง ถ้าไม่พบใส่ "-"
        
        ข้อมูลชื่อเจ้าของที่บอทขูดมาได้เบื้องต้น (Extracted Owner Name):
        {parsed_data.get('owner_name', '-')}
        
        ข้อมูลเบอร์โทรเสริม (Extracted Phone):
        {parsed_data.get('extracted_phone', '-')}
        
        ข้อความดิบ (Raw Text Input):
        {parsed_data.get('raw_text', '')}
        
        ข้อมูลการติดต่อจากไอคอน (Contact Info From Icon):
        {parsed_data.get('contact_icon', 'ไม่พบ')}
        
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
            "house_number": "-"
        }
