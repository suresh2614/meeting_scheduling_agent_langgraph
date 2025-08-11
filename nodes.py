"""Graph nodes for the meeting scheduler workflow - Fixed for interrupts"""

import re
from typing import Dict, Any, List
from datetime import datetime, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from state import SchedulingState, Attendee, TimeSlot, MeetingRoom
from knowledge import AvailabilityKnowledge
from tools import calendar_tool
from config import settings
from prompts import get_system_prompt
from meeting_rooms import MeetingRoomManager
import json
from json import loads, JSONDecodeError
from langgraph.types import interrupt
from Backend.calendar_tools import create_calendar_event

# Initialize components
llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0.1,
    api_key=settings.openai_api_key
)

knowledge = AvailabilityKnowledge()
room_manager = MeetingRoomManager()

async def parse_request_node(state: SchedulingState) -> Dict[str, Any]:
    """Parse the initial meeting request to extract attendees and basic info"""
    
    last_message = state["messages"][-1].content if state["messages"] else ""
    
    # Use LLM to extract information
    extraction_prompt = f"""
Extract meeting details from this request: "{last_message}"

Today's date is {datetime.today().strftime('%Y-%m-%d')} and current time is {datetime.now().strftime('%H:%M')}.

Return as JSON:
{{
    "attendee_names": ["name1", "name2"],
    "requested_date": "YYYY-MM-DD or relative date",
    "requested_time": "HH:MM",
    "duration_minutes": 60,
    "urgency": "urgent/normal"
}}

If any field is not mentioned, use null.
"""
    
    response = await llm.ainvoke([HumanMessage(content=extraction_prompt)])

    content = response.content.strip()
    # Remove markdown code block if present
    if content.startswith("```"):
        content = content.split("```")[-2] if content.count("```") >= 2 else content
        content = content.replace("json", "").strip()
    try:
        extracted = json.loads(content)
        if extracted.get("attendee_names") is None:
            extracted["attendee_names"] = []
    except Exception:
        extracted = {
            "attendee_names": [],
            "requested_date": None,
            "requested_time": None,
            "duration_minutes": 60,
            "urgency": "normal"
        }
    
    # Look up attendees in knowledge base
    attendees = []
    attendee_names = extracted.get("attendee_names", [])
    
    if attendee_names:
        search_results = await knowledge.get_available_slots(attendee_names)
        
        # Extract email from search results
        for user in search_results:
            attendees.append({
                "name": user['name'],
                "email": user['email'],
                "base_location": user['base_location'],
                "timezone": "Asia/Kolkata",
                "is_available": None
            })
    
    # Update state
    state["meeting_request"]["raw_request"] = last_message
    state["meeting_request"]["requested_date"] = extracted.get("requested_date")
    state["meeting_request"]["requested_time"] = extracted.get("requested_time")
    state["meeting_request"]["duration_minutes"] = extracted.get("duration_minutes", 60)
    state["attendees"] = attendees
    
    # Generate acknowledgment
    if attendees:
        names = [a["name"] for a in attendees]
        names_str = " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + f", and {names[-1]}"
        
        response_text = f"I'll coordinate schedules for {names_str}."
        
        if extracted.get("urgency") == "urgent":
            response_text = f"Prioritizing this urgent meeting with {names_str}."
    else:
        response_text = "I couldn't identify the attendees. Could you please specify who should attend?"
    
    state["messages"].append(AIMessage(content=response_text))
    state["current_step"] = "check_availability"
    
    return state

async def check_availability_node(state: SchedulingState) -> Dict[str, Any]:
    """Check availability for all attendees using LLM to analyze and find common free slots"""
    
    # Get current context
    attendees = state.get("attendees", [])
    meeting_request = state.get("meeting_request", {})
    user_message = state.get("messages", [])[-1].content if state.get("messages") else ""
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Get availability data for attendees
    availability_data = {}
    if attendees:
        attendee_names = [att.get("name", att) if isinstance(att, dict) else att for att in attendees]
        try:
            user_data_list = await knowledge.get_available_slots(attendee_names)
            for i, name in enumerate(attendee_names):
                if i < len(user_data_list) and user_data_list[i]:
                    availability_data[name] = user_data_list[i]
                else:
                    # Default availability data
                    availability_data[name] = {
                        "calendar_events": {},
                        "ooo_dates": [],
                        "travel_dates": [],
                        "preferred_hours": {"start": "09:00", "end": "17:00"},
                        "timezone": "UTC"
                    }
        except Exception as e:
            print(f"Error fetching availability data: {e}")
            # Use default data for all attendees
            for name in attendee_names:
                availability_data[name] = {
                    "calendar_events": {},
                    "ooo_dates": [],
                    "travel_dates": [],
                    "preferred_hours": {"start": "09:00", "end": "17:00"},
                    "timezone": "UTC"
                }
    
    # LLM Prompt for availability analysis
    prompt = f"""You are an intelligent meeting scheduler. Analyze the meeting request and attendee availability to find optimal meeting times.

    CONTEXT:
    - Current date and time: {current_datetime}
    - Business hours: 8:00 AM - 5:00 PM (Monday-Friday)
    - Default meeting duration: 30 minutes if not specified
    - Time slots are in 30-minute increments

    INPUT:
    User Message: "{user_message}"
    Meeting Request: {json.dumps(meeting_request, indent=2)}
    Attendees: {json.dumps(attendees, indent=2)}
    Availability Data: {json.dumps(availability_data, indent=2)}

    TASK:
    1. Parse the meeting request and extract meeting details
    2. Check each attendee's availability for conflicts (OOO, travel, existing meetings)
    3. Find available 30-minute time slots within business hours
    4. Consolidate consecutive slots and rank by preference
    5. Generate a natural response with suggestions

    RESPOND ONLY WITH VALID JSON in this exact format:
    {{
    "status": "success|no_availability|attendee_unavailable|need_clarification",
    "parsed_request": {{
        "title": "extracted meeting title or purpose",
        "requested_date": "YYYY-MM-DD or 'today'|'tomorrow'|'flexible'",
        "requested_time": "HH:MM or 'morning'|'afternoon'|'flexible'",
        "duration_minutes": 30,
        "priority": "high|medium|low"
    }},
    "target_date": "YYYY-MM-DD",
    "unavailable_attendees": [
        {{
        "name": "attendee name",
        "reason": "out_of_office|traveling|busy",
        "details": "specific conflict description"
        }}
    ],
    "available_slots": [
        {{
        "date": "YYYY-MM-DD",
        "start_time": "HH:MM",
        "end_time": "HH:MM",
        "duration_minutes": 30,
        "confidence": "high|medium|low"
        }}
    ],
    "response_message": "Natural language response to user with specific times and dates",
    "follow_up_question": "Question if more info needed (null if none)",
    "next_step": "select_time|reschedule|gather_more_info"
    }}

    RULES:
    - Skip past times if checking today
    - If attendees unavailable, suggest next available date
    - Present max 3 best available slots
    - Use specific dates (e.g., "Thursday, August 8th") not relative terms
    - Be conversational and helpful in response_message
    - If missing critical info, ask follow-up questions"""
    
    try:
        # Call LLM
        response = await llm.ainvoke(prompt)
        
        # Parse LLM response
        try:
            llm_result = json.loads(response.content)
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            # Try to clean up the response and parse again
            cleaned_content = response.content.strip()
            if cleaned_content.startswith("```"):
                cleaned_content = cleaned_content.split("```")[-2] if cleaned_content.count("```") >= 2 else cleaned_content
                cleaned_content = cleaned_content.replace("json", "").strip()
            try:
                llm_result = json.loads(cleaned_content)
            except Exception as e2:
                print(f"Second JSON parsing error: {e2}")
                # Fallback response
                state["messages"].append(AIMessage(content="I need more information to check availability. Could you please specify the attendees and preferred time?"))
                state["current_step"] = "gather_more_info"
                return state
        
        # Update state with parsed information
        if llm_result.get("parsed_request"):
            parsed = llm_result["parsed_request"]
            state["meeting_request"].update({
                "title": parsed.get("title"),
                "requested_date": parsed.get("requested_date"),
                "requested_time": parsed.get("requested_time"),
                "duration_minutes": parsed.get("duration_minutes", 30),
                "priority": parsed.get("priority", "medium")
            })
        
        # Update available slots
        state["available_slots"] = llm_result.get("available_slots", [])
        state["unavailable_attendees"] = llm_result.get("unavailable_attendees", [])
        if llm_result.get("target_date"):
            state["target_date"] = llm_result["target_date"]
        
        # Store follow-up question and suggestions
        if llm_result.get("follow_up_question"):
            state["follow_up_question"] = llm_result["follow_up_question"]
        if llm_result.get("suggested_actions"):
            state["suggested_actions"] = llm_result["suggested_actions"]
        
        # Add response message
        response_message = llm_result.get("response_message", "I've checked availability for you.")
        state["messages"].append(AIMessage(content=response_message))
        
        # Set next step - this is key for interrupts to work
        if llm_result.get("available_slots"):
            state["current_step"] = "select_time"  # This will trigger human_time_selection interrupt
        else:
            state["current_step"] = llm_result.get("next_step", "select_time")
        
        # Store full LLM analysis for debugging
        state["llm_analysis"] = llm_result
        
        return state
        
    except Exception as e:
        print(f"Error in LLM availability check: {e}")
        
        # Fallback to original logic if LLM fails
        if not attendees:
            state["messages"].append(AIMessage(content="Please specify who should attend the meeting."))
            state["current_step"] = "gather_more_info"
            return state
        
        # Simple fallback availability check
        requested_date = state["meeting_request"].get("requested_date", "today")
        if requested_date == "today":
            check_date = datetime.today()
        elif requested_date == "tomorrow":
            check_date = datetime.today() + timedelta(days=1)
        else:
            try:
                check_date = datetime.strptime(requested_date, "%Y-%m-%d")
            except:
                check_date = datetime.today()
        
        # Basic availability slots (fallback)
        current_time = datetime.now()
        available_slots = []
        
        for hour in range(9, 17):  # 9 AM to 5 PM
            for minute in [0, 30]:
                slot_start = check_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                slot_end = slot_start + timedelta(minutes=30)
                
                # Skip past times
                if check_date.date() == datetime.today().date() and slot_start <= current_time:
                    continue
                
                available_slots.append({
                    "date": check_date.strftime("%Y-%m-%d"),
                    "start_time": slot_start.strftime("%H:%M"),
                    "end_time": slot_end.strftime("%H:%M"),
                    "duration_minutes": 30
                })
                
                if len(available_slots) >= 3:  # Limit to 3 slots
                    break
            if len(available_slots) >= 3:
                break
        
        state["available_slots"] = available_slots
        
        if available_slots:
            date_str = "today" if check_date.date() == datetime.today().date() else check_date.strftime("%A, %B %d")
            slots_text = "\n".join([f"• {slot['start_time']} - {slot['end_time']}" for slot in available_slots])
            response_text = f"Here are some available times {date_str}:\n{slots_text}\n\nWhich time works for you?"
            state["current_step"] = "select_time"  # This will trigger human_time_selection interrupt
        else:
            response_text = f"No availability found on {check_date.strftime('%B %d')}. Should I check the next day?"
            state["current_step"] = "gather_more_info"
        
        state["messages"].append(AIMessage(content=response_text))
        
        return state

async def gather_details_node(state: SchedulingState) -> Dict[str, Any]:
    """Gather meeting details like time selection and agenda - Updated for interrupts"""
    
    last_message = state["messages"][-1].content
    
    # Check if this is a time selection (fallback if interrupt doesn't work)
    time_pattern = r'(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?'
    time_match = re.search(time_pattern, last_message.lower())
    
    if time_match and not state.get("selected_slot"):
        # Parse time selection
        selected_time = None
        for slot in state.get("available_slots", []):
            slot_time_str = slot["start_time"].lower().replace(":", "")
            message_time_str = last_message.lower().replace(":", "").replace(" ", "")
            
            if slot_time_str in message_time_str or message_time_str in slot_time_str:
                selected_time = slot
                break
        
        if selected_time:
            state["selected_slot"] = selected_time
            state["current_step"] = "get_agenda"  # This will trigger human_agenda_input interrupt
            response_text = "Perfect! What's the meeting topic?"
        else:
            response_text = "I couldn't match that time. Please choose from the available slots."
            state["current_step"] = "select_time"  # Back to time selection
    
    elif not state.get("meeting_agenda"):
        # This should be the agenda
        state["meeting_agenda"] = last_message
        
        # Generate meeting title
        title_prompt = f"""
Generate a brief, professional meeting title (max 5 words) for this agenda: "{last_message}"

Return only the title, nothing else.
"""
        
        title_response = await llm.ainvoke([HumanMessage(content=title_prompt)])
        state["meeting_title"] = title_response.content.strip()
        state["meeting_description"] = f"Meeting scheduled by AI Assistant. Agenda: {last_message}"
        
        # Move to format determination
        state["current_step"] = "determine_format"
        return await determine_format_node(state)
    
    else:
        response_text = "What would you like to do?"
        state["current_step"] = "gather_more_info"
    
    state["messages"].append(AIMessage(content=response_text))
    
    return state

async def determine_format_node(state: SchedulingState) -> Dict[str, Any]:
    """Determine meeting format and suggest room options"""
    
    # Analyze attendee locations
    location_attendees = {}
    for attendee in state["attendees"]:
        location = attendee.get("base_location", "Unknown")
        if location not in location_attendees:
            location_attendees[location] = []
        location_attendees[location].append(attendee["name"])
    
    # Store location analysis
    state["attendee_locations"] = location_attendees
    unique_locations = list(location_attendees.keys())
    state["same_location"] = len(unique_locations) == 1 and "Unknown" not in unique_locations
    
    num_attendees = len(state["attendees"])
    
    if state["same_location"]:
        # Same location - offer both options
        location = unique_locations[0]
        room_options = room_manager.get_available_rooms(location, num_attendees)
        
        response = f"All attendees are in {location}. Do you prefer a virtual or in-person meeting?"
        
        if room_options:
            response += "\nIf in-person, here are available cabins:"
            for room in room_options:
                response += f"\n   • floor {room['floor']} Cabin {room['cabin_id']} ({room['capacity']}-person capacity)"
        
        state["available_rooms"] = room_options
        
    else:
        # Different locations - virtual recommended but offer in-person options
        response = "Since "
        
        # Format attendee locations nicely
        location_strs = []
        for loc, names in location_attendees.items():
            if len(names) == 1:
                location_strs.append(f"{names[0]} ({loc})")
            else:
                names_str = " and ".join(names) if len(names) == 2 else ", ".join(names[:-1]) + f" and {names[-1]}"
                location_strs.append(f"{names_str} ({loc})")
        
        response += " and ".join(location_strs)
        response += " are from different locations, a virtual meeting is recommended."
        
        # Get room options for each location
        room_options_by_location = {}
        for location, names in location_attendees.items():
            if location != "Unknown":
                rooms = room_manager.get_available_rooms(location, len(names))
                if rooms:
                    room_options_by_location[location] = rooms
        
        if room_options_by_location:
            response += "\nAlternatively, would you like to book in-person cabins at their respective locations?"
            response += "\nHere are the available options at each location:"
            
            for location, rooms in room_options_by_location.items():
                room_strs = []
                for room in rooms:
                    room_strs.append(f"floor {room['floor']} Cabin {room['cabin_id']}")
                response += f"\n• {location}: {', '.join(room_strs)}"
        
        state["available_rooms"] = []  # Will be populated based on user choice
    
    state["messages"].append(AIMessage(content=response))
    state["current_step"] = "format_selection"  # This will trigger human_format_selection interrupt
    
    return state

async def process_format_selection_node(state: SchedulingState) -> Dict[str, Any]:
    """Process user's format selection - fallback if interrupt doesn't work"""
    
    last_message = state["messages"][-1].content.lower()
    
    if "virtual" in last_message or "online" in last_message or "video" in last_message:
        state["meeting_format"] = "virtual"
        response = "Virtual meeting confirmed."
        state["current_step"] = "confirm_meeting"  # This will trigger human_confirmation interrupt
        
    elif "person" in last_message or "office" in last_message or "cabin" in last_message:
        state["meeting_format"] = "in-person"
        
        # Check if user specified a cabin
        cabin_pattern = r'([A-Z]\d[A-Z]\d)'  # Matches patterns like M1C5, C2C3
        cabin_match = re.search(cabin_pattern, last_message.upper())
        
        if cabin_match:
            cabin_id = cabin_match.group(1)
            # Find the room details
            for room in state.get("available_rooms", []):
                if room["cabin_id"] == cabin_id:
                    state["meeting_room"] = room
                    response = f"{cabin_id} is reserved (capacity: {room['capacity']})."
                    state["current_step"] = "confirm_meeting"  # This will trigger human_confirmation interrupt
                    break
            else:
                response = "I couldn't find that cabin. Please choose from the available options."
                state["current_step"] = "format_selection"
        else:
            # If same location, pick the first suitable room
            if state.get("same_location") and state.get("available_rooms"):
                state["meeting_room"] = state["available_rooms"][0]
                response = f"{state['meeting_room']['cabin_id']} is reserved (capacity: {state['meeting_room']['capacity']})."
                state["current_step"] = "confirm_meeting"  # This will trigger human_confirmation interrupt
            else:
                response = "Please specify which cabin you'd like to book."
                state["current_step"] = "format_selection"
    else:
        response = "Please specify if you'd like a virtual meeting or choose an in-person cabin."
        state["current_step"] = "format_selection"
    
    state["messages"].append(AIMessage(content=response))
    
    return state

async def confirm_meeting_node(state: SchedulingState) -> Dict[str, Any]:
    """Present final meeting details for confirmation - fallback if interrupt doesn't work"""
    
    # Format details
    attendee_names = [a["name"] for a in state["attendees"]]
    names_str = " and ".join(attendee_names) if len(attendee_names) <= 2 else ", ".join(attendee_names[:-1]) + f", and {attendee_names[-1]}"
    
    slot = state["selected_slot"]
    date = datetime.strptime(slot["date"], "%Y-%m-%d")
    date_str = "today" if date.date() == datetime.today().date() else date.strftime("%A, %B %d")
    
    if state.get("meeting_format") == "in-person" and state.get("meeting_room"):
        location_str = f"{state['meeting_room']['cabin_id']} at {state['meeting_room']['location']}"
    else:
        location_str = "virtual"
    
    confirmation_text = f"Scheduling: {state.get('meeting_title', 'Meeting')} on {date_str} at {slot['start_time']} with {names_str} ({location_str}). Sending invites now!"
    
    state["messages"].append(AIMessage(content=confirmation_text))
    state["current_step"] = "send_invites"
    state["confirmation_status"] = True
    
    return state

async def send_invites_node(state: SchedulingState) -> Dict[str, Any]:
    """Send calendar invitations"""
    
    # This node will trigger the tool call
    slot = state["selected_slot"]
    
    # Determine location
    meeting_room = state.get("meeting_room")
    if meeting_room and "cabin_id" in meeting_room:
        location = meeting_room["cabin_id"]
    else:
        location = "Online"

    # Now create the tool call message
    tool_call_message = create_calendar_event(
        title=state.get("meeting_title"),
        date=slot["date"],
        time=slot["start_time"],
        duration_hours=slot.get("duration_hours", 1),
        attendee_emails=[a["email"] for a in state["attendees"]],
        location=location,
        description=state.get("meeting_description", "")
    )

    
    state["meeting_details"] = {
        "title": state.get("meeting_title", "Meeting"),
        "date": slot["date"],
        "time": slot["start_time"],
        "duration_minutes": slot["duration_minutes"],
        "attendee_emails": [a["email"] for a in state["attendees"]],
        "location": state["meeting_room"]["cabin_id"] if state.get("meeting_room") else "Online",
        "description": state.get("meeting_description", "Meeting scheduled by AI Assistant")
    }
    
    state["messages"].append(tool_call_message)
    tool_call_message_json  = json.loads(tool_call_message)
    if tool_call_message_json.get("emails_sent", False):
        formatted_details = format_meeting_details(state['meeting_details'])
        state["messages"].append(AIMessage(content=f"✅ Invites sent successfully!<br><br>{formatted_details}"))
        # state["messages"].append(AIMessage(content=f"Invites sent successfully! Below are the details:\n\n  {state['meeting_details']}"))
    state["current_step"] = "complete"
    
    return state
import json

def format_meeting_details(details):
    if isinstance(details, dict):
        formatted = "📋 <strong>Meeting Details:</strong><br>"
        for key, value in details.items():
            # Convert snake_case to Title Case
            display_key = key.replace('_', ' ').title()
            formatted += f"• <strong>{display_key}:</strong> {value}<br>"
        return formatted
    else:
        return f"📋 <strong>Meeting Details:</strong><br>{details}"

# Updated routing function - removed async since it's used as conditional edge
def route_conversation(state: SchedulingState) -> str:
    """Route to the appropriate node based on current state"""
    
    current_step = state.get("current_step", "parse_request")
    
    if current_step == "parse_request":
        return "parse_request"
    elif current_step == "check_availability":
        return "check_availability"
    elif current_step == "select_time":
        return "human_time_selection"  # Will trigger interrupt
    elif current_step == "get_agenda":
        return "human_agenda_input"   # Will trigger interrupt
    elif current_step == "gather_details":
        return "gather_details"
    elif current_step == "determine_format":
        return "determine_format"
    elif current_step == "format_selection":
        return "human_format_selection"  # Will trigger interrupt
    elif current_step == "process_format_selection":
        return "process_format_selection"
    elif current_step == "confirm_meeting":
        return "human_confirmation"     # Will trigger interrupt
    elif current_step == "send_invites":
        return "send_invites"
    elif current_step == "complete":
        return "END"
    else:
        return "parse_request"
# Add interrupt nodes for human intervention
async def human_time_selection_node(state: SchedulingState) -> Dict[str, Any]:
    """
    LLM-enhanced time slot selection with human intervention,
    relying entirely on the LLM for intent parsing.
    """
    available_slots = state.get("available_slots", [])
    if not available_slots:
        state["current_step"] = "check_availability"
        return state
 
    # Format slots for display to user
    slots_display = []
    for i, slot in enumerate(available_slots, 1):
        slots_display.append(f"{i}. {slot['date']} from {slot['start_time']} to {slot['end_time']}")
 
    # Create a friendly, natural-language message for the user
    display_message = f"""
    I've found these available time slots for you:
    
    {chr(10).join(slots_display)}
    
    Please let me know which one you prefer. You can simply say "the second one," "the morning slot," or type the number, like '1'. If none of these work, just let me know you'd like to see different times and I'll find more options.
    """
 
    # Prepare interrupt data for human input
    interrupt_data = {
        "message": display_message,
        "available_slots": available_slots,
        "context": "time_selection"
    }
 
    user_selection = interrupt(interrupt_data)
 
    # Use LLM to intelligently parse user input as the primary method
    llm_prompt = f"""
    The user has been presented with the following time slots:
    {chr(10).join(slots_display)}
    
    The user responded: "{user_selection}"
    
    Analyze the user's response to determine their intent. Respond with ONLY a JSON object.
    - If the user wants to book a slot, identify which one based on their description (e.g., "morning slot," "the 2pm one," or "1").
    - If the user wants to see different times, identify this as a 'reschedule' action.
    - If the intent is unclear, identify this as 'invalid'.
    
    Respond with a JSON object in this format:
    {{
        "action": "select_slot|reschedule|invalid",
        "slot_number": <1-based on user response, null otherwise>,
        "confidence": <0.0-1.0, your confidence in the action>
    }}
    """
 
    try:
        
 
        llm_response = await llm.ainvoke([
            SystemMessage(content=llm_prompt),
            HumanMessage(content=str(user_selection))
        ])
 
        try:
            parsed_response = loads(llm_response.content.strip())
        except JSONDecodeError:
            # print(f"JSON parsing error: {e}")
            # Try to clean up the response and parse again
            cleaned_content = llm_response.content.strip()
            if cleaned_content.startswith("```"):
                cleaned_content = cleaned_content.split("```")[-2] if cleaned_content.count("```") >= 2 else cleaned_content
                cleaned_content = cleaned_content.replace("json", "").strip()
                parsed_response = json.loads(cleaned_content)
            # If the LLM response is not valid JSON, treat it as an invalid action.
            # parsed_response = {"action": "invalid", "slot_number": None, "confidence": 0.0}
 
        action = parsed_response.get("action", "invalid")
        slot_number = parsed_response.get("slot_number")
        confidence = parsed_response.get("confidence", 0.0)
 
        # Process based on LLM interpretation
        if action == "select_slot" and isinstance(slot_number, int) and confidence > 0.6:
            if 1 <= slot_number <= len(available_slots):
                selected_slot = available_slots[slot_number - 1]
                state["selected_slot"] = selected_slot
                state["current_step"] = "get_agenda"
                state["messages"].append({"content": f"✅ Got it! I've selected the slot: {selected_slot['date']} {selected_slot['start_time']} - {selected_slot['end_time']}.", "type": "system"})
                return state
            else:
                # LLM suggested a number outside the valid range
                action = "invalid"
 
        if action == "reschedule" and confidence > 0.7:
            state["current_step"] = "check_availability"
            state["messages"].append({"content": "Sure, I'll find some different times for you.", "type": "system"})
            return state
 
        # If LLM response is invalid or confidence is low, respond directly to the user
        state["current_step"] = "select_time"
        state["messages"].append({"content": "Sorry, I couldn't understand your choice. Please try again by selecting a number or telling me you want to find different times.", "type": "system"})
        return state
 
    except Exception:
        # Final, simple fallback if the LLM call itself fails
        state["current_step"] = "select_time"
        state["messages"].append({"content": "Something went wrong. Please enter a valid slot number or let me know if you need different times.", "type": "system"})
        return state

async def human_format_selection_node(state: SchedulingState) -> Dict[str, Any]:
    """Human intervention for meeting format selection"""
    
    # Prepare format options based on attendee locations
    attendee_locations = state.get("attendee_locations", {})
    available_rooms = state.get("available_rooms", [])
    same_location = state.get("same_location", False)
    
    format_options = ["virtual"]
    room_info = []
    
    if same_location and available_rooms:
        format_options.append("in-person")
        for room in available_rooms:
            room_info.append(f"Cabin {room['cabin_id']} (Floor {room['floor']}, {room['capacity']} capacity)")
    
    # Prepare interrupt data
    interrupt_data = {
        "message": f"""Please choose meeting format:",
        "attendee_locations": {attendee_locations},
        "same_location": {same_location},
        "format_options": {format_options},
        "available_rooms": {room_info},
        "instructions": "Type 'virtual' for online meeting, 'in-person' for office meeting, or specify cabin ID (e.g., 'M1C5')"""
    }
    
    # Get user's format choice
    user_choice = interrupt(interrupt_data)
    
    choice_lower = str(user_choice).lower()
    
    if "virtual" in choice_lower:
        state["meeting_format"] = "virtual"
        state["current_step"] = "confirm_meeting"
        state["messages"].append({
            "content": "Virtual meeting selected", 
            "type": "system"
        })
        return state
        
    elif "person" in choice_lower or any(room["cabin_id"].lower() in choice_lower for room in available_rooms):
        # Find selected room
        selected_room = None
        cabin_id_upper = str(user_choice).upper()
        
        for room in available_rooms:
            if room["cabin_id"] in cabin_id_upper or "person" in choice_lower:
                selected_room = room
                break
        
        if selected_room or "person" in choice_lower:
            state["meeting_format"] = "in-person"
            state["meeting_room"] = selected_room or (available_rooms[0] if available_rooms else None)
            state["current_step"] = "confirm_meeting"
            state["messages"].append({
                "content": f"In-person meeting selected: {selected_room['cabin_id'] if selected_room else 'TBD'}", 
                "type": "system"
            })
            return state
    
    # Invalid selection, ask again
    state["current_step"] = "format_selection"
    state["messages"].append({
        "content": "Please choose 'virtual', 'in-person', or specify a cabin ID.", 
        "type": "system"
    })
    return state

async def human_agenda_input_node(state: SchedulingState) -> Dict[str, Any]:
    """Human intervention for meeting agenda input"""
    
    selected_slot = state.get("selected_slot", {})
    attendees = state.get("attendees", [])
    
    # Prepare interrupt data
    interrupt_data = {
        "message": "Please provide the meeting topic/agenda:",
        "selected_slot": selected_slot,
        "attendees": [att.get("name", att) for att in attendees],
        "instructions": "Enter the meeting purpose, topic, or agenda"
    }
    
    # Get meeting agenda from user
    user_agenda = interrupt(interrupt_data)
    
    if user_agenda and str(user_agenda).strip():
        # Generate meeting title from agenda
        agenda_text = str(user_agenda).strip()
        
        # Simple title generation
        title_words = agenda_text.split()[:4]  
        meeting_title = " ".join(title_words).title()
        if len(agenda_text.split()) > 4:
            meeting_title += "..."
        
        state["meeting_agenda"] = agenda_text
        state["meeting_title"] = meeting_title
        state["meeting_description"] = f"Meeting scheduled via AI Assistant. Agenda: {agenda_text}"
        state["current_step"] = "determine_format"
        state["messages"].append({
            "content": f"Meeting topic set: {agenda_text}", 
            "type": "system"
        })
        return state
    else:
        # Empty agenda, ask again
        state["current_step"] = "get_agenda"
        state["messages"].append({
            "content": "Please provide a meeting topic or agenda.", 
            "type": "system"
        })
        return state

async def human_confirmation_node(state: SchedulingState) -> Dict[str, Any]:
    """Human intervention for final meeting confirmation"""
    
    # Prepare meeting summary
    meeting_title = state.get("meeting_title", "Meeting")
    selected_slot = state.get("selected_slot", {})
    attendees = state.get("attendees", [])
    meeting_format = state.get("meeting_format", "virtual")
    meeting_room = state.get("meeting_room", {})
    meeting_agenda = state.get("meeting_agenda", "")
    
    attendee_names = [att.get("name", att) for att in attendees]
    
    # Format meeting details
    date_str = selected_slot.get("date", "TBD")
    time_str = f"{selected_slot.get('start_time', 'TBD')} - {selected_slot.get('end_time', 'TBD')}"
    location_str = meeting_room.get("cabin_id", "Online") if meeting_format == "in-person" else "Virtual"
    
    # Prepare interrupt data
    interrupt_data = {
        "message":  f"""Please review and confirm this meeting:

            Meeting Details:
            - Title: {meeting_title}
            - Date: {date_str}
            - Time: {time_str}
            - Attendees: {attendee_names}
            - Location: {location_str}
            - Agenda: {meeting_agenda}

            Instructions:
            Type 'confirm' to proceed, 'cancel' to abort, or 'edit' to make changes.
            """
    }
    
    # Get user confirmation
    user_confirmation = interrupt(interrupt_data)
    
    confirmation_lower = str(user_confirmation).lower()
    
    if "confirm" in confirmation_lower:
        state["confirmation_status"] = True
        state["current_step"] = "send_invites"
        state["messages"].append({
            "content": "Meeting confirmed! Sending invitations...", 
            "type": "system"
        })
        return state
    elif "cancel" in confirmation_lower:
        state["confirmation_status"] = False
        state["current_step"] = "complete"
        state["messages"].append({
            "content": "Meeting cancelled.", 
            "type": "system"
        })
        return state
    elif "edit" in confirmation_lower:
        state["current_step"] = "get_agenda"
        state["messages"].append({
            "content": "Let's edit the meeting details. What's the meeting topic?", 
            "type": "system"
        })
        return state
    else:
        state["current_step"] = "confirm_meeting"
        state["messages"].append({
            "content": "Please type 'confirm', 'cancel', or 'edit'.", 
            "type": "system"
        })
        return state

# Updated routing function to handle interrupts
def route_with_interrupts(state: SchedulingState) -> str:
    """Enhanced routing function that includes interrupt points"""
    
    current_step = state.get("current_step", "parse_request")
    
    if current_step == "parse_request":
        return "parse_request"
    elif current_step == "check_availability":
        return "check_availability"
    elif current_step == "select_time":
        return "human_time_selection"
    elif current_step == "get_agenda":
        return "human_agenda_input"
    elif current_step == "gather_details":
        return "gather_details"
    elif current_step == "determine_format":
        return "determine_format"
    elif current_step == "format_selection":
        return "human_format_selection"
    elif current_step == "process_format_selection":
        return "process_format_selection"
    elif current_step == "confirm_meeting":
        return "human_confirmation"
    elif current_step == "send_invites":
        return "send_invites"
    elif current_step == "complete":
        return "END"
    else:
        return "parse_request"