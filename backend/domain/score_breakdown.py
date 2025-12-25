from dataclasses import dataclass
from typing import Optional, Dict


@dataclass
class ScoreBreakdown:
    technical: float
    macro: float
    event_adjustment: float
    total: float
    label: str
    technical_details: Dict
    macro_details: Dict
    event_details: Dict
    effective_event: Optional[Dict] = None
