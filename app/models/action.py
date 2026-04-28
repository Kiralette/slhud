"""
Action models — the shape of data for player actions and need state.
"""

from pydantic import BaseModel
from typing import Optional


class ActionRequest(BaseModel):
    """What the HUD sends when a player uses an object."""
    object_key: str           # matches a key in config.yaml objects section
    duration_seconds: int = 0 # how long they used the object (for time-based gains)
    quality_tier: int = 0     # 0=basic, 1=good, 2=great, 3=excellent


class NeedState(BaseModel):
    """The current state of one need."""
    need_key: str
    value: float
    zone: str        # "thriving", "okay", "struggling", "critical", "zero"


class LogEntry(BaseModel):
    """One line of activity history shown in the phone app."""
    action_text: str
    delta: float
    need_key: Optional[str]
    timestamp: str


class ActionResponse(BaseModel):
    """What the server sends back after processing an action."""
    success: bool
    needs: list[NeedState]       # all 7 needs, updated
    log_entries: list[LogEntry]  # what just happened (shown in the app)
    moodlets_applied: list[str]  # any new moodlets triggered
    message: str                 # human-readable summary e.g. "You ate cookies +15 Hunger"
