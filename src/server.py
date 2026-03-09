import os
import sys
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import logging

# Ensure src is in the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import run_scraping_job

app = FastAPI(title="Scraper Agent API")

# ตั้งค่า Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ScrapeResponse(BaseModel):
    status: str
    data: Optional[dict] = None
    message: Optional[str] = None

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Scraper Agent is running smoothly with FastAPI!"}

@app.post("/run-scraper", response_model=ScrapeResponse)
async def start_scraping(max_items: int = 10):
    """
    Endpoint สำหรับรับคำสั่งจาก Cloud Scheduler
    """
    logger.info("Received request to run scraper via FastAPI.")
    
    results = {}
    try:
        # 1. ขูด "บ้าน"
        logger.info(f"Starting to scrape 'บ้าน' (Max {max_items} items)")
        res_house = run_scraping_job(selected_type="บ้าน", selected_zone="บางนา", max_items_override=max_items)
        results['บ้าน'] = res_house
        
        # 2. ขูด "คอนโด"
        logger.info(f"Starting to scrape 'คอนโด' (Max {max_items} items)")
        res_condo = run_scraping_job(selected_type="คอนโด", selected_zone="บางนา", max_items_override=max_items)
        results['คอนโด'] = res_condo
        
        logger.info(f"Scraping completed successfully! Results: {results}")
        return {"status": "success", "data": results}
        
    except Exception as e:
        logger.error(f"Error during scraping job: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run(app, host='0.0.0.0', port=port)
