"""LangChain tools wrapper for calendar functionality"""

from langchain.tools import Tool
from typing import List, Dict, Any
import json
from Backend.calendar_tools import create_calendar_event as original_create_event

def create_calendar_event_wrapper(
    title: str,
    date: str,
    time: str,
    duration_minutes: int,
    attendee_emails: List[str],
    location: str = "Online",
    description: str = "Meeting scheduled by AI Assistant"
) -> Dict[str, Any]:
    """Wrapper for the original calendar event creation function"""
    
    result_json = original_create_event(
        title=title,
        date=date,
        time=time,
        duration_minutes=duration_minutes,
        attendee_emails=attendee_emails,
        location=location,
        description=description
    )
    
    return json.loads(result_json)

# Create LangChain tool
calendar_tool = Tool(
    name="create_calendar_event",
    description="""Create a calendar event and send invitations.
    Args:
        title: Meeting title
        date: Date in YYYY-MM-DD format
        time: Time in HH:MM format
        duration_minutes: Duration in minutes
        attendee_emails: List of attendee email addresses
        location: Meeting location (default: "Online")
        description: Meeting description
    """,
    func=create_calendar_event_wrapper
)