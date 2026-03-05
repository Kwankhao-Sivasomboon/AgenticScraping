# Agentic AI Scraping (Hybrid Architecture)

ระบบ Agent ดึงข้อมูลอสังหาริมทรัพย์อัตโนมัติ (Scraping) ด้วย Playwright และส่งให้ AI (Gemini 1.5 Flash) วิเคราะห์ข้อมูลเพื่อคัดกรอง Lead ก่อนจะบันทึกลง Firestore (ฐานข้อมูลหลัก) และ Google Sheets (แดชบอร์ดแสดงผล)

## โครงสร้างโปรเจกต์ (Project Structure)
```
PainpointToday_AgentScraping/
├── src/
│   ├── main.py
│   ├── scraper_agent.py
│   ├── evaluator_agent.py
│   ├── firestore_service.py
│   └── sheets_service.py
├── .env.example
├── credentials.json (ต้องนำมาใส่เอง)
├── playwright_state.json (ระบบจะสร้างอัตโนมัติเมื่อ Login สำเร็จครั้งแรก)
├── requirements.txt
├── Dockerfile
└── README.md
```

## สถาปัตยกรรม (Architecture)
- **Ingestion Phase:** `Playwright` + `Stealth` จำลองการเปิดเบราว์เซอร์และคลิกทะลุเข้าหน้า Detail เพื่อดึงข้อมูลแบบหลีกเลี่ยง Bot Detection (พร้อมจำ Session Cookies)
- **Validation Phase:** `Firestore` เช็คข้อมูลซ้ำ (Deduplication) ด้วย Listing ID ไม่ทำให้กิน Resources เหมือนตอนเช็คจาก Sheets
- **Intelligence Phase:** `Gemini 1.5 Flash` ดึงข้อมูลดิบ (Raw Text มากกว่า 5000 ตัวอักษร) เพื่อหาชื่อผู้ขาย, เบอร์โทร, ราคา, ชั้น, สเปคห้อง/บ้าน
- **Storage & Delivery Phase:** `Firestore` (จัดเก็บข้อมูลดิบและผลวิเคราะห์) + `Google Sheets` (แดชบอร์ดแสดงผล)

## การติดตั้งและการรันบนเครื่อง Local (ทดสอบ)

1. **สร้างและเปิดใช้งาน Virtual Environment (Conda หรือ venv):**
   ```powershell
   conda create -n agent_scraping python=3.11 -y
   conda activate agent_scraping
   ```

2. **ติดตั้ง Libraries และเบราว์เซอร์ Playwright:**
   ```powershell
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **ตั้งค่า Environment Variables:**
   - คัดลอกไฟล์ `.env.example` แล้วเปลี่ยนชื่อเป็น `.env`
   - นำไฟล์ `credentials.json` จาก Google Cloud Platform (เปิดใช้ Sheets API และ Firestore) มาวางไว้ที่โฟลเดอร์รันงาน (Root)
   - เติมข้อมูลใน `.env` ให้ครบถ้วน (โดยเฉพาะ `LIVING_INSIDER_USERNAME`, `LIVING_INSIDER_PASSWORD` และ `GOOGLE_API_KEY`)

4. **เริ่มการทำงาน:**
   ```powershell
   python src/main.py
   ```
   *(หมายเหตุ: ในการรันครั้งแรก ระบบจะทำการ Login เข้าสู่ระบบและบันทึก Session ไว้ใน `playwright_state.json` การรันครั้งถัดไปจะไม่ต้อง Login ใหม่)*

---

## การเตรียมระบบขึ้น Google Cloud Run / VPS (Docker)

โปรเจกต์นี้มาพร้อมกับ `Dockerfile` ที่ปรับจูนให้ตัว Playwright สามารถทำงานแบบ Headless บนเซิร์ฟเวอร์ Cloud ได้อย่างไร้ปัญหา

### 1. การสร้าง Docker Image
เปิด Terminal หรือ Command Prompt ในโฟลเดอร์ Root แล้วรันคำสั่ง:
```bash
docker build -t agent-scraper .
```

### 2. การทดสอบรันใน Docker (Local)
รัน Container โดยจำลองการดึงไฟล์ `.env`, `credentials.json` และ session state มาเสียบเข้า Container:
```bash
docker run --rm \
  -v ${PWD}/.env:/app/.env \
  -v ${PWD}/credentials.json:/app/credentials.json \
  -v ${PWD}/playwright_state.json:/app/playwright_state.json \
  agent-scraper
```

### การตั้งค่า Google Cloud Run (ข้อควรรู้)
- **Memory:** Playwright ค่อนข้างกิน Memory แนะนำให้ตั้งค่า Memory สำหรับ Cloud Run อย่างน้อย **1GB - 2GB** ขึ้นไป
- **Timeout:** การ Scraping ใช้เวลาค่อนข้างนาน (ถ้าดึงหลาย URL) ให้ปรับ Timeout ของ Cloud Run จากค่าเริ่มต้น (5 นาที) เป็น **15-30 นาที**
- **Credentials:** บน Cloud Run สามารถกำหนดให้ Service ผูกกับ Google Cloud IAM ได้เลยโดยตรง ทำให้ไม่ต้องแนบไฟล์ `credentials.json` แบบเดียวกับ Local
- **Proxy:** การเข้าเว็บบน Cloud มักจะโดนบล็อกไอพี ให้ตั้งค่า `USE_PROXY=true` และกรอกรายละเอียด Proxy Server ในตัวแปร `.env` เสมอ

## ผู้พัฒนา
**Simai (PainpointToday)** - Agentic AI Solutions
