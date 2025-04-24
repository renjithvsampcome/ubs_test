import os
import json
import logging
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
import pandas as pd
from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Form
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
import uvicorn
from pathlib import Path

# Import our custom modules
from agents.agent_factory import create_agent_system
from utils.pdf_generator import create_webpage_snapshot
from data_access.alert_reader import load_alerts_from_csv, load_alerts_from_database
from models.alert_models import Alert, AlertProcessingResult
from market_validators.market_validator import MarketTypeValidator
from share_validators.outstanding_share_validator import OutstandingShareValidator

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create the FastAPI app
app = FastAPI(
    title="UBS Compliance Agent System",
    description="AI agent system for processing global shareholder reporting alerts",
    version="1.0.0",
)

# Initialize storage directories
EVIDENCE_DIR = Path("evidence")
RESULTS_DIR = Path("results")
EVIDENCE_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# Create our agent system
agent_system = create_agent_system()

class ProcessAlertRequest(BaseModel):
    alert_id: str
    isin: str
    security_name: str
    outstanding_shares_system: Optional[int] = None
    
class ProcessAlertsRequest(BaseModel):
    alerts: List[ProcessAlertRequest]

class AlertResponse(BaseModel):
    alert_id: str
    is_true_positive: bool
    justification: str
    evidence_path: Optional[str] = None

@app.post("/process_alert", response_model=AlertResponse)
async def process_alert(alert: ProcessAlertRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"Processing alert {alert.alert_id} for ISIN {alert.isin}")
        
        # Convert to our internal Alert model
        alert_obj = Alert(
            alert_id=alert.alert_id,
            isin=alert.isin,
            security_name=alert.security_name,
            outstanding_shares_system=alert.outstanding_shares_system
        )
        
        # Process the alert
        result = await agent_system.process_alert(alert_obj)
        
        # Generate evidence PDF in the background (if needed)
        if result.evidence_url:
            pdf_path = EVIDENCE_DIR / f"{alert.alert_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            background_tasks.add_task(create_webpage_snapshot, result.evidence_url, str(pdf_path))
            result.evidence_path = str(pdf_path)
        
        return AlertResponse(
            alert_id=alert.alert_id,
            is_true_positive=result.is_true_positive,
            justification=result.justification,
            evidence_path=result.evidence_path
        )
    
    except Exception as e:
        logger.error(f"Error processing alert: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process_alerts_batch", response_model=List[AlertResponse])
async def process_alerts_batch(request: ProcessAlertsRequest, background_tasks: BackgroundTasks):
    results = []
    for alert_req in request.alerts:
        try:
            result = await process_alert(alert_req, background_tasks)
            results.append(result)
        except Exception as e:
            logger.error(f"Error processing alert {alert_req.alert_id}: {e}")
            results.append(AlertResponse(
                alert_id=alert_req.alert_id,
                is_true_positive=False,
                justification=f"Error during processing: {str(e)}",
                evidence_path=None
            ))
    
    return results

@app.get("/evidence/{alert_id}")
async def get_evidence(alert_id: str):
    # Find the most recent evidence for this alert
    files = list(EVIDENCE_DIR.glob(f"{alert_id}_*.pdf"))
    if not files:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    latest_file = max(files, key=lambda p: p.stat().st_mtime)
    return FileResponse(str(latest_file), media_type="application/pdf")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)