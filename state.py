"""State definitions for the LangGraph meeting scheduler"""

from typing import TypedDict, List, Optional, Dict, Any, Annotated
from datetime import datetime
from langgraph.graph.message import add_messages

class MeetingRequest(TypedDict):
    """User's meeting request details"""
    raw_request: str
    requested_date: Optional[str]
    requested_time: Optional[str]
    duration_minutes: Optional[int]
    meeting_type: Optional[str]

class Attendee(TypedDict):
    """Attendee information"""
    name: str
    email: str
    base_location: Optional[str]
    timezone: Optional[str]
    is_available: Optional[bool]

class TimeSlot(TypedDict):
    """Available time slot"""
    date: str
    start_time: str
    end_time: str
    duration_minutes: int

class MeetingRoom(TypedDict):
    """Meeting room details"""
    location: str
    floor: str
    cabin_id: str
    capacity: int

class SchedulingState(TypedDict):
    """Main state for the scheduling workflow"""
    # Conversation
    messages: Annotated[List[Dict[str, Any]], add_messages]
    
    # Session info
    session_id: str
    user_id: str
    user_name: str
    
    # Workflow state
    current_step: str
    
    # Meeting request
    meeting_request: MeetingRequest
    
    # Extracted information
    attendees: List[Attendee]
    available_slots: List[TimeSlot]
    selected_slot: Optional[TimeSlot]
    
    # Meeting details
    meeting_title: Optional[str]
    meeting_description: Optional[str]
    meeting_agenda: Optional[str]
    meeting_format: Optional[str]  # "in-person" or "virtual"
    meeting_room: Optional[MeetingRoom]
    available_rooms: Optional[List[MeetingRoom]]  # For user selection
    
    # Location analysis
    attendee_locations: Optional[Dict[str, List[str]]]  # location -> [attendee names]
    same_location: Optional[bool]
    
    # Status
    confirmation_status: Optional[bool]
    error: Optional[str]
    
    # Metadata
    created_at: datetime
    updated_at: datetime

    meeting_details: Optional[Dict[str, Any]]  # Additional details like agenda, notes, etc.
    llm_analysis: Optional[Dict[str, Any]] 
    need_more_details: Optional[bool] = False
    question: Optional[str] = None
    follow_up_question: Optional[str] = None  # For human interrupts
    human_node_conv: List[Dict[str, Any]] = []  # Store conversation history for context