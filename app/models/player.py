"""
Player models — defines the shape of data coming in and going out.
Pydantic automatically validates that requests have the right fields
and the right types, and gives nice error messages if they don't.
"""

from pydantic import BaseModel
from typing import Optional


class RegisterRequest(BaseModel):
    """What the HUD sends when an avatar attaches for the first time."""
    avatar_uuid: str
    display_name: str


class RegisterResponse(BaseModel):
    """What the server sends back after registering a new player."""
    success: bool
    player_id: int
    token: str
    display_name: str
    is_new: bool          # True if just created, False if already existed


class PlayerResponse(BaseModel):
    """A player's full profile."""
    player_id: int
    avatar_uuid: str
    display_name: str
    registered_at: str
    last_seen: str
    is_online: bool
