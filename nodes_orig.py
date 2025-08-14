"""Graph nodes for the meeting scheduler workflow"""

import re
from typing import Dict, Any, List
from datetime import datetime, timedelta
# from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from state import SchedulingState, Attendee, TimeSlot, MeetingRoom
from knowledge import AvailabilityKnowledge
from tools import calendar_tool
from config import settings
from prompts import get_system_prompt
from meeting_rooms import MeetingRoomManager
import json

# Initialize components
llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0.1,
    api_key=settings.openai_api_key
)

knowledge = AvailabilityKnowledge()
room_manager = MeetingRoomManager()

# Tool node
# tool_node = ToolNode([calendar_tool])

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

    import json
    content = response.content.strip()
    # Remove markdown code block if present
    if content.startswith("```"):
        # Remove triple backticks and optional language specifier
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
    # for name in extracted.get("attendee_names", []):
        # Search for user in knowledge base
        # search_results = await knowledge.search(f"user {name}")
    search_results = await knowledge.get_available_slots(attendee_names)
        
    # Extract email from search results
    for user in search_results:
        # if "Email:" in user.page_content:
        #     email_match = re.search(r'Email: ([^\n]+)', user.page_content)
        #     name_match = re.search(r'Name: ([^\n]+)', user.page_content)
        #     location_match = re.search(r'Base Location: ([^\n]+)', user.page_content)
            
            # if email_match:
        attendees.append({
            "name": user['name'],
            "email": user['email'],
            "base_location": user['base_location'],
            "timezone": "Asia/Kolkata",
            "is_available": None
        })
        # break
    
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

# async def check_availability_node(state: SchedulingState) -> Dict[str, Any]:
#     """Check availability for all attendees and find common free slots"""
    
#     attendees = state["attendees"]
#     if not attendees:
#         state["messages"].append(AIMessage(content="Please specify who should attend the meeting."))
#         return state
    
#     # Determine date to check
#     requested_date = state["meeting_request"]["requested_date"]
#     if not requested_date or requested_date == "today":
#         check_date = datetime.today()
#     elif requested_date == "tomorrow":
#         check_date = datetime.today() + timedelta(days=1)
#     else:
#         try:
#             check_date = datetime.strptime(requested_date, "%Y-%m-%d")
#         except:
#             check_date = datetime.today()
    
#     # Check each attendee's availability
#     all_busy_slots = []
#     unavailable_attendees = []
    
#     for attendee in attendees:
#         user_data = await knowledge.get_available_slots([attendee["name"]])
#         user_data = user_data[0]
#         if user_data:
#             # Check OOO and travel
#             date_str = check_date.strftime("%Y-%m-%d")
#             if date_str in user_data.get("ooo_dates", []):
#                 unavailable_attendees.append((attendee["name"], "out of office"))
#                 continue
#             if date_str in user_data.get("travel_dates", []):
#                 unavailable_attendees.append((attendee["name"], "traveling"))
#                 continue
            
#             # Get busy slots
#             calendar_events = user_data.get("calendar_events", {}).get(date_str, [])
#             for event in calendar_events:
#                 all_busy_slots.append(event["slot"])
    
#     # If anyone is unavailable, suggest next day
#     if unavailable_attendees:
#         # Only mention specific names for OOO/travel
#         for name, reason in unavailable_attendees:
#             if reason == "traveling":
#                 response_text = f"{name} is traveling on {check_date.strftime('%B %d')}. "
#             else:
#                 response_text = f"{name} is unavailable on {check_date.strftime('%B %d')}. "
#             break
        
#         # Find next available date
#         next_date = check_date + timedelta(days=1)
#         response_text += f"Would you like to check {next_date.strftime('%A, %B %d')} instead?"
        
#         state["messages"].append(AIMessage(content=response_text))
#         return state
    
#     # Find available slots
#     business_start = 8
#     business_end = 17
#     duration_minutes = state["meeting_request"]["duration_minutes"]
    
#     available_slots = []
#     current_time = datetime.now()
    
#     for hour in range(business_start, business_end):
#         for minute in [0, 30]:
#             slot_start = check_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
#             slot_end = slot_start + timedelta(minutes=duration_minutes)
            
#             # Skip if in the past
#             if check_date.date() == datetime.today().date() and slot_start <= current_time:
#                 continue
            
#             # Skip if end time exceeds business hours
#             if slot_end.hour > business_end or (slot_end.hour == business_end and slot_end.minute > 0):
#                 continue
            
#             # Check if slot conflicts with any busy time
#             slot_str = f"{slot_start.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}"
            
#             is_free = True
#             for busy_slot in all_busy_slots:
#                 if slot_str in busy_slot or busy_slot in slot_str:
#                     is_free = False
#                     break
            
#             if is_free:
#                 available_slots.append({
#                     "date": check_date.strftime("%Y-%m-%d"),
#                     "start_time": slot_start.strftime("%H:%M"),
#                     "end_time": slot_end.strftime("%H:%M"),
#                     "duration_minutes": duration_minutes
#                 })
    
#     # Consolidate consecutive slots
#     consolidated_slots = []
#     if available_slots:
#         current_block = available_slots[0].copy()
        
#         for slot in available_slots[1:]:
#             if slot["start_time"] == current_block["end_time"]:
#                 current_block["end_time"] = slot["end_time"]
#                 current_block["duration_minutes"] += slot["duration_minutes"]
#             else:
#                 consolidated_slots.append(current_block)
#                 current_block = slot.copy()
        
#         consolidated_slots.append(current_block)
    
#     state["available_slots"] = consolidated_slots[:3]  # Max 3 options
    
#     # Generate response
#     if consolidated_slots:
#         date_str = "today" if check_date.date() == datetime.today().date() else check_date.strftime("%A, %B %d")
        
#         slots_text = "\n".join([
#             f"• {slot['start_time']} - {slot['end_time']}"
#             for slot in consolidated_slots[:3]
#         ])
        
#         response_text = f"Everyone's free during these times {date_str}:\n{slots_text}\n\nWhich time works?"
#     else:
#         response_text = f"No availability found on {check_date.strftime('%B %d')}. Should I check the next day?"
    
#     state["messages"].append(AIMessage(content=response_text))
#     state["current_step"] = "select_time"
    
#     return state

async def check_availability_node(state: SchedulingState) -> Dict[str, Any]:
    """Check availability for all attendees using LLM to analyze and find common free slots"""
    
    # from langchain_openai import ChatOpenAI
    # from langchain_core.prompts import ChatPromptTemplate
    # import json
    
    # # Initialize LLM
    # llm = ChatOpenAI(model="gpt-4", temperature=0.1, max_tokens=2000)
    
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
        
        # Set next step
        state["current_step"] = llm_result.get("next_step", "select_time")
        
        # Store full LLM analysis for debugging
        state["llm_analysis"] = llm_result
        
        return state
        
    except Exception as e:
        print(f"Error in LLM availability check: {e}")
        
        # Fallback to original logic if LLM fails
        if not attendees:
            state["messages"].append(AIMessage(content="Please specify who should attend the meeting."))
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
        else:
            response_text = f"No availability found on {check_date.strftime('%B %d')}. Should I check the next day?"
        
        state["messages"].append(AIMessage(content=response_text))
        state["current_step"] = "select_time"
        
        return state

async def gather_details_node(state: SchedulingState) -> Dict[str, Any]:
    """Gather meeting details like time selection and agenda"""
    
    last_message = state["messages"][-1].content
    
    # Check if this is a time selection
    time_pattern = r'(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?'
    time_match = re.search(time_pattern, last_message.lower())
    
    if time_match and not state["selected_slot"]:
        # Parse time selection
        selected_time = None
        for slot in state["available_slots"]:
            slot_time_str = slot["start_time"].lower().replace(":", "")
            message_time_str = last_message.lower().replace(":", "").replace(" ", "")
            
            if slot_time_str in message_time_str or message_time_str in slot_time_str:
                selected_time = slot
                break
        
        if selected_time:
            state["selected_slot"] = selected_time
            response_text = "Perfect! What's the meeting topic?"
        else:
            response_text = "I couldn't match that time. Please choose from the available slots."
    
    elif not state["meeting_agenda"]:
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
    state["current_step"] = "format_selection"
    
    return state

async def process_format_selection_node(state: SchedulingState) -> Dict[str, Any]:
    """Process user's format selection"""
    
    last_message = state["messages"][-1].content.lower()
    
    if "virtual" in last_message or "online" in last_message or "video" in last_message:
        state["meeting_format"] = "virtual"
        response = "Virtual meeting confirmed."
        state["current_step"] = "confirm_meeting"
        
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
                    state["current_step"] = "confirm_meeting"
                    break
            else:
                response = "I couldn't find that cabin. Please choose from the available options."
        else:
            # If same location, pick the first suitable room
            if state["same_location"] and state.get("available_rooms"):
                state["meeting_room"] = state["available_rooms"][0]
                response = f"{state['meeting_room']['cabin_id']} is reserved (capacity: {state['meeting_room']['capacity']})."
                state["current_step"] = "confirm_meeting"
            else:
                response = "Please specify which cabin you'd like to book."
    else:
        response = "Please specify if you'd like a virtual meeting or choose an in-person cabin."
    
    state["messages"].append(AIMessage(content=response))
    
    return state

async def confirm_meeting_node(state: SchedulingState) -> Dict[str, Any]:
    """Present final meeting details for confirmation"""
    
    # Format details
    attendee_names = [a["name"] for a in state["attendees"]]
    names_str = " and ".join(attendee_names) if len(attendee_names) <= 2 else ", ".join(attendee_names[:-1]) + f", and {attendee_names[-1]}"
    
    slot = state["selected_slot"]
    date = datetime.strptime(slot["date"], "%Y-%m-%d")
    date_str = "today" if date.date() == datetime.today().date() else date.strftime("%A, %B %d")
    
    if state["meeting_format"] == "in-person" and state.get("meeting_room"):
        location_str = f"{state['meeting_room']['cabin_id']} at {state['meeting_room']['location']}"
    else:
        location_str = "virtual"
    
    confirmation_text = f"Scheduling: {state['meeting_title']} on {date_str} at {slot['start_time']} with {names_str} ({location_str}). Sending invites now!"
    
    state["messages"].append(AIMessage(content=confirmation_text))
    state["current_step"] = "send_invites"
    state["confirmation_status"] = True
    
    return state

async def send_invites_node(state: SchedulingState) -> Dict[str, Any]:
    """Send calendar invitations"""
    
    # This node will trigger the tool call
    slot = state["selected_slot"]
    
    tool_call_message = AIMessage(
        content="I'll send the calendar invitations now.",
        tool_calls=[{
            "name": "create_calendar_event",
            "args": {
                "title": state["meeting_title"],
                "date": slot["date"],
                "time": slot["start_time"],
                "duration_minutes": slot["duration_minutes"],
                "attendee_emails": [a["email"] for a in state["attendees"]],
                "location": state["meeting_room"]["cabin_id"] if state.get("meeting_room") else "Online",
                "description": state["meeting_description"]
            },
            "id": "calendar_invite_1"
        }]
    )
    state["meeting_details"] = {
        "title": state["meeting_title"],
        "date": slot["date"],
        "time": slot["start_time"],
        "duration_minutes": slot["duration_minutes"],
        "attendee_emails": [a["email"] for a in state["attendees"]],
        "location": state["meeting_room"]["cabin_id"] if state.get("meeting_room") else "Online",
        "description": state["meeting_description"]}
    
    state["messages"].append(tool_call_message)
    state["current_step"] = "complete"
    
    return state

async def route_conversation(state: SchedulingState) -> str:
    """Route to the appropriate node based on current state"""
    
    current_step = state.get("current_step", "parse_request")
    
    if current_step == "parse_request":
        return "parse_request"
    elif current_step == "check_availability":
        return "check_availability"
    elif current_step == "select_time" or current_step == "get_agenda":
        return "gather_details"
    elif current_step == "determine_format":
        return "determine_format"
    elif current_step == "format_selection":
        return "process_format_selection"
    elif current_step == "confirm_meeting":
        return "confirm_meeting"
    elif current_step == "send_invites":
        return "send_invites"
    elif current_step == "complete":
        return "END"
    else:
        return "parse_request"