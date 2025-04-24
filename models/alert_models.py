from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class Alert(BaseModel):
    """Model representing an alert from the UBS system"""
    alert_id: str
    isin: str
    security_name: str
    outstanding_shares_system: Optional[int] = None
    received_timestamp: datetime = Field(default_factory=datetime.now)
    
    class Config:
        from_attributes = True

class AlertProcessingResult(BaseModel):
    """Model representing the result of processing an alert"""
    alert_id: str
    is_true_positive: bool
    justification: str
    evidence_url: Optional[str] = None
    evidence_path: Optional[str] = None
    processing_timestamp: datetime = Field(default_factory=datetime.now)
    
    class Config:
        from_attributes = True

# market_validators/market_validator.py
