from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class ARIEvent(BaseModel):
    """A generic ARI event."""
    type: str
    application: str
    timestamp: str
    asterisk_id: Optional[str] = None
    channel: Optional[Dict[str, Any]] = None
    playback: Optional[Dict[str, Any]] = None
    bridge: Optional[Dict[str, Any]] = None
    endpoint: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    digit: Optional[str] = None
    cause: Optional[str] = None
    userevent: Optional[Dict[str, Any]] = None
    class Config:
        extra = 'allow'
