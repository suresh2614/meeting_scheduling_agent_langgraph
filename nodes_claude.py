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
    

    extraction_prompt = f"""Extract meeting details from this request: "{last_message}"

Rules:
1. First, check if the user is simply greeting (e.g., says "hello" or "hi").  
   - If yes, reply exactly with: "Hello! How can I assist you with scheduling a meeting today?"  
   - Do not return JSON in this case.

2. Otherwise, assume the user is requesting to schedule a meeting.

3. Today's date is {datetime.today().strftime('%Y-%m-%d')} and current time is {datetime.now().strftime('%H:%M')}.  
   - If the user does not specify a meeting date, set "requested_date" to today's date.  
   - If the user specifies a relative date (e.g., "tomorrow", "next Monday"), keep it in that form.

4. Return the result as JSON in this exact structure (no markdown, no triple backticks):
{{
    "attendee_names": ["name1", "name2"],
    "requested_date": "YYYY-MM-DD or relative date",
    "requested_time": "HH:MM",
    "duration_minutes": 30,  # Default to 30 minutes if not specified, if duration is mentioned, use that value
    "urgency": "urgent/normal",
    "follow_up_question": "Dynamic question based on what's missing or unclear"
}}

5. If any field is not mentioned, set it to null.

6. For 'follow_up_question':
   - If the request is unrelated to meeting scheduling, generate a friendly question to guide them back to meeting scheduling.
   - If attendee_names is empty/null, ask for attendee names naturally in context.
   - Make the question conversational and specific to the missing info.
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
            "urgency": "normal",
            "follow_up_question": "Hello! How can I assist you with scheduling a meeting today?"
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
    else:
        # Use the LLM-generated follow-up question, with fallback if needed
        follow_up_message = extracted.get("follow_up_question", "Hello! How can I assist you with scheduling a meeting today?")
        
        state["follow_up_question"] = follow_up_message
        state["messages"].append(AIMessage(content=follow_up_message))
        state["current_step"] = "complete"
        state["need_more_details"] = True
        state["question"] = last_message
        return state
    
    # Update state
    state["meeting_request"]["raw_request"] = last_message
    state["meeting_request"]["requested_date"] = extracted.get("requested_date")
    state["meeting_request"]["requested_time"] = extracted.get("requested_time")
    state["meeting_request"]["duration_minutes"] = extracted.get("duration_minutes", 60)
    state["attendees"] = attendees
    state["need_more_details"] = False
    
    # Generate acknowledgment
    if attendees:
        names = [a["name"] for a in attendees]
        names_str = " and ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + f", and {names[-1]}"
        
        response_text = f"I'll coordinate schedules for {names_str}."
        
        if extracted.get("urgency") == "urgent":
            response_text = f"Prioritizing this urgent meeting with {names_str}."
    
    
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
                        "preferred_hours": {"start": "08:00", "end": "17:00"},
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
                    "preferred_hours": {"start": "08:00", "end": "17:00"},
                    "timezone": "UTC"
                }

    # Enhanced prompt with better conflict handling
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

CRITICAL INSTRUCTIONS FOR AVAILABILITY CHECKING:

1. **Parse the meeting request** and extract meeting details. If date is not specified, assume 'today'.

2. **Check UNAVAILABILITY (mark as unavailable only for these cases):**
   - ooo_dates: If requested date is in this list, attendee is OUT OF OFFICE
   - travel_dates: If requested date is in this list, attendee is TRAVELING

3. **Handle CALENDAR CONFLICTS (DO NOT mark as unavailable):**
   - calendar_events: If there are conflicting meetings on the requested date/time
   - INSTEAD: Find alternative time slots that work around the conflicts
   - Generate available_slots that avoid conflicting meeting times
   - Only mark attendee as unavailable if they are out of office or traveling

4. **Time Slot Logic:**
   - If specific time requested and there are conflicts: suggest alternative times
   - If no specific time requested: find best available slots avoiding conflicts
   - Always provide at least 3 alternative slots if attendees are available (not OOO/traveling)

5. **Response Rules:**
   - unavailable_attendees: ONLY for OOO or travel, NOT for calendar conflicts
   - available_slots: Include slots that work around calendar conflicts
   - If attendees have conflicts but are not OOO/traveling, still provide available slots

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
            "reason": "out_of_office|traveling",
            "details": "specific reason with dates"
        }}
    ],
    "calendar_conflicts": [
        {{
            "attendee": "name",
            "conflict_time": "HH:MM-HH:MM",
            "conflict_details": "existing meeting description"
        }}
    ],
    "available_slots": [
        {{
            "date": "YYYY-MM-DD",
            "start_time": "HH:MM",
            "end_time": "HH:MM",
            "duration_minutes": 30,
            "confidence": "high|medium|low",
            "note": "works around conflicts" 
        }}
    ],
    "response_message": "Natural language response explaining availability and conflicts",
    "follow_up_question": "Question about conflicts or null if none",
    "next_step": "human_meeting_details|reschedule|gather_more_info"
}}

EXAMPLES OF PROPER CONFLICT HANDLING:

Example 1 - Calendar Conflict (NOT unavailable):
- John has a meeting 2:00-3:00 PM on requested date
- Result: Include available_slots for 9:00 AM, 10:00 AM, 4:00 PM, etc.
- Do NOT add John to unavailable_attendees

Example 2 - Out of Office (Unavailable):
- Sarah is in ooo_dates for requested date  
- Result: Add Sarah to unavailable_attendees, no available_slots
- Ask for different date

Example 3 - Mixed Scenario:
- John has calendar conflict, Sarah is OOO
- Result: Add only Sarah to unavailable_attendees
- Suggest rescheduling because Sarah is unavailable

RULES:
- Calendar conflicts = find alternative slots
- OOO/Travel = mark as unavailable, suggest new date
- Always try to provide available slots unless attendees are truly unavailable
- Be specific about conflicts vs unavailability in response messages
"""

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

        # Debug logging
        print(f"LLM Result: {json.dumps(llm_result, indent=2)}")
        
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
        
        # Update target date
        if llm_result.get("target_date"):
            state["target_date"] = llm_result["target_date"]
        
        # Handle unavailable attendees case (only for OOO/travel)
        unavailable_attendees = llm_result.get("unavailable_attendees", [])
        calendar_conflicts = llm_result.get("calendar_conflicts", [])
        
        if unavailable_attendees:
            print(f"Found unavailable attendees (OOO/Travel): {unavailable_attendees}")
            
            # Store unavailable attendee information
            state["unavailable_attendees"] = unavailable_attendees
            state["available_slots"] = []  # Clear available slots for truly unavailable attendees
            
            # Get response messages from LLM
            response_message = llm_result.get("response_message", "")
            follow_up_question = llm_result.get("follow_up_question", "")
            
            # Combine response_message and follow_up_question
            if response_message and follow_up_question:
                combined_message = f"{response_message} {follow_up_question}"
            elif follow_up_question:
                combined_message = follow_up_question
            elif response_message:
                combined_message = response_message
            else:
                # Fallback message generation with specific names
                unavailable_names = [ua.get("name", "Unknown") for ua in unavailable_attendees]
                if len(unavailable_names) == 1:
                    combined_message = f"Unfortunately, {unavailable_names[0]} is not available on the requested date. Would you like to choose a different date?"
                else:
                    combined_message = f"Unfortunately, {', '.join(unavailable_names)} are not available on the requested date. Would you like to choose a different date?"
            
            state["follow_up_question"] = combined_message
            state["messages"].append(AIMessage(content=combined_message))
            state["current_step"] = "human_meeting_details"
            
            return state
        
        # Handle case where attendees are available (even with calendar conflicts)
        available_slots = llm_result.get("available_slots", [])
        if available_slots:
            state["available_slots"] = available_slots
            state["unavailable_attendees"] = []  # Clear any previous unavailable attendees
            state["calendar_conflicts"] = calendar_conflicts  # Store conflicts for reference
            
            # Add response message that mentions conflicts if any
            response_message = llm_result.get("response_message", "")
            if not response_message:
                if calendar_conflicts:
                    conflict_names = list(set([c.get("attendee", "Someone") for c in calendar_conflicts]))
                    response_message = f"Found some calendar conflicts for {', '.join(conflict_names)}, but here are available time slots that work around them:"
                else:
                    response_message = "I've found available time slots for the meeting."
            
            state["messages"].append(AIMessage(content=response_message))
            state["current_step"] = "human_meeting_details"
            
        else:
            # No available slots and no explicitly unavailable attendees
            response_message = llm_result.get("response_message", "No suitable time slots found. Please suggest alternative dates or times.")
            state["messages"].append(AIMessage(content=response_message))
            
            next_step = llm_result.get("next_step", "human_meeting_details")
            state["current_step"] = next_step if next_step in ["gather_more_info", "reschedule"] else "human_meeting_details"
        
        # Store full LLM analysis for debugging
        state["llm_analysis"] = llm_result
        
        return state
        
    except Exception as e:
        print(f"Error in LLM availability check: {e}")
        
        # Fallback to basic availability check if LLM fails
        if not attendees:
            state["messages"].append(AIMessage(content="Please specify who should attend the meeting."))
            state["current_step"] = "gather_more_info"
            return state
        
        # Simple fallback availability slots
        requested_date = state["meeting_request"].get("requested_date", "today")
        print(f"*****Requested date: {requested_date}*****")
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
        print(f"====Available slots: {available_slots}===")
        if available_slots:
            date_str = "today" if check_date.date() == datetime.today().date() else check_date.strftime("%A, %B %d")
            slots_text = "\n".join([f"• {slot['start_time']} - {slot['end_time']}" for slot in available_slots])
            response_text = f"Here are some available times {date_str}:\n{slots_text}\n\nWhich time works for you?"
            state["current_step"] = "human_meeting_details"
        else:
            response_text = f"No availability found on {check_date.strftime('%B %d')}. Should I check the next day?"
            state["current_step"] = "gather_more_info"
        
        state["messages"].append(AIMessage(content=response_text))
        
        return state

async def human_meeting_details_node(state: SchedulingState) -> Dict[str, Any]:
    """
    Human intervention to collect all meeting details: time selection, agenda, format, and confirmation
    Uses LLM to process all user input and make decisions with better context awareness
    """
   
    # Get context data
    available_slots = state.get("available_slots", [])
    attendees = state.get("attendees", [])
    attendee_locations = {}
    attendee_emails = [att.get("email") for att in attendees if "email" in att]
    attendee_names = [att.get("name") for att in attendees if "name" in att]
    
    # Analyze attendee locations
    for attendee in attendees:
        location = attendee.get("base_location", "Unknown")
        print(f"======Attendee {attendee['name']} is based in {location}=====\n")
        if location not in attendee_locations:
            attendee_locations[location] = []
        attendee_locations[location].append(attendee["name"])
   
    unique_locations = list(attendee_locations.keys())
    print(f"====Unique locations: {unique_locations}===\n")
    same_location = len(unique_locations) == 1 and "Unknown" not in unique_locations
    num_attendees = len(attendees)
   
    # Get available rooms
    available_rooms = []
    room_options_by_location = {}
    all_rooms = ""
 
    if same_location:
        location = unique_locations[0]
        available_rooms = room_manager.get_available_rooms(location, num_attendees)
        if available_rooms:
            room_options_by_location[location] = available_rooms
           
            print(f"====Inside same location block==== Available rooms at {location}:")
            for i, room in enumerate(available_rooms, 1):
                room_str = f"Option {i}: Floor {room['floor']}, Cabin ID {room['cabin_id']}, Capacity {room['capacity']}<br>"
                all_rooms += room_str + "\n"
                print(" ", room_str)
        else:
            print(f"====Inside same location block==== No rooms available at {location}")
    else:
        for location, names in attendee_locations.items():
            if location != "Unknown":
                rooms = room_manager.get_available_rooms(location, len(names))
                if rooms:
                    room_options_by_location[location] = rooms
                    print(f"Available rooms at {location}:")
                    for i, room in enumerate(rooms, 1):
                        room_str = f"Option {i}: Floor {room['floor']}, Cabin ID {room['cabin_id']}, Capacity {room['capacity']}"
                        all_rooms += room_str + "\n"
                        print(" ", room_str)

    # Check if this is a follow-up conversation or initial request
    is_followup = bool(state.get("human_node_conv"))
    last_system_message = None
    
    if is_followup:
        # Find the last system message to understand current context
        for conv in reversed(state["human_node_conv"]):
            for k, v in conv.items():
                if k == "System":
                    last_system_message = v
                    break
            if last_system_message:
                break
    
    # Determine what information we already have
    existing_details = {
        "selected_slot": state.get("selected_slot"),
        "meeting_title": state.get("meeting_title"),
        "meeting_agenda": state.get("meeting_agenda"),
        "meeting_format": state.get("meeting_format"),
        "meeting_room": state.get("meeting_room")
    }
    
    # Check if we're dealing with unavailable attendees
    unavailable_attendees = state.get("unavailable_attendees", [])
    follow_up_question = state.get("follow_up_question")
    
    # Build appropriate message based on context
    if is_followup and last_system_message:
        # This is a follow-up, use the last system message as context
        interrupt_data = {"message": last_system_message}
        print(f"Using follow-up message: {last_system_message}")
    elif unavailable_attendees or follow_up_question:
        # Handle unavailable attendees case
        if follow_up_question:
            interrupt_data = {"message": follow_up_question}
        else:
            # Build message about unavailable attendees
            unavailable_names = [ua.get("name", "Unknown") for ua in unavailable_attendees]
            message = f"Unfortunately, {', '.join(unavailable_names)} {'is' if len(unavailable_names) == 1 else 'are'} not available on the requested date. "
            message += "Would you like to:\n1. Choose a different date\n2. Proceed without them\n3. Cancel the meeting"
            interrupt_data = {"message": message}
        print(f"Using unavailable attendees message")
    else:
        # This is initial request, build comprehensive message
        message_lines = []
     
        # 1. Participants
        message_lines.append("1. Can you please confirm these are the correct participants:<br>")
        for name, email in zip(attendee_names, attendee_emails):
            message_lines.append(f"&nbsp;&nbsp;* {name} ({email})<br>")
     
        # 2. Available slots
        if available_slots:
            slots_text = "\n".join(
                [f"&nbsp;* {slot['start_time']} - {slot['end_time']} ET<br>" for slot in available_slots]
            )
            message_lines.append(
                f"<br>2. Both are available today. Here are the available time slots for today, {available_slots[0]['date']}:<br>{slots_text}<br>"
            )
        else:
            message_lines.append("<br>2. No available slots found. Please specify a different date or time.<br>")
     
        # 3. Duration
        message_lines.append(
            "3. How long should the meeting be? I will default to a 30 min meeting unless you tell me otherwise<br><br>"
        )
     
        # 4. Meeting format
        if same_location and room_options_by_location:
            rooms = ", ".join(room_options_by_location)
            message_lines.append(
                f"4. Since {', '.join(attendee_names)} are in the same location, please confirm the meeting room, I will default to virtual unless you specify otherwise: <br>{all_rooms}<br>"
            )
        else:
            message_lines.append(
                f"4. Since {', '.join(attendee_names)} are in different locations, the meeting will be virtual unless you tell me otherwise!<br><br>"
            )
     
        # 5. Topic
        message_lines.append("5. What is the topic of discussion?<br>")
        
        interrupt_data = {"message": "\n".join(message_lines)}
        print(f"Using initial comprehensive message")

    # Get user input
    user_input = interrupt(interrupt_data)
    
    # Initialize conversation history if not exists
    if "human_node_conv" not in state:
        state["human_node_conv"] = []
    
    state["human_node_conv"].append({"User": user_input})
    
    # Build conversation context for LLM
    conversation_context = ""
    if state.get("human_node_conv"):
        conversation_context = "\n".join(
            f"{list(entry.keys())[0]}: {list(entry.values())[0]}"
            for entry in state["human_node_conv"]
        )
    
    # Check if user is requesting a date change (reschedule scenario)
    is_reschedule_request = any(word in user_input.lower() for word in [
        "august 30", "30th", "tomorrow", "next", "different date", "another date", 
        "reschedule", "change date", "monday", "tuesday", "wednesday", "thursday", "friday"
    ])
    
    # Enhanced LLM prompt that handles rescheduling properly
    llm_prompt = f"""
You are an AI meeting scheduler processing user input to finalize meeting details.
 
CONTEXT:
Available time slots: {json.dumps(available_slots, indent=2)}
Attendees: {[att.get('name') for att in attendees]}
Attendee locations: {json.dumps(attendee_locations, indent=2)}
Same location: {same_location}
Available rooms: {json.dumps(available_rooms, indent=2)}
Room options by location: {json.dumps(room_options_by_location, indent=2)}
Unavailable attendees: {json.dumps(unavailable_attendees, indent=2)}
Is reschedule request: {is_reschedule_request}

EXISTING MEETING DETAILS:
- Selected slot: {existing_details.get('selected_slot', 'Not set')}
- Meeting title: {existing_details.get('meeting_title', 'Not set')}
- Meeting agenda: {existing_details.get('meeting_agenda', 'Not set')}
- Meeting format: {existing_details.get('meeting_format', 'Not set')}
- Meeting room: {existing_details.get('meeting_room', 'Not set')}

CONVERSATION HISTORY: 
{conversation_context}

CURRENT USER INPUT: "{user_input}"
 
TASK: Analyze the user input. The user might be:
1. **Requesting a new date**: If user mentions specific dates (August 30th, tomorrow, etc.), this is a RESCHEDULE REQUEST
2. Selecting a time slot from available options
3. Providing meeting topic/agenda
4. Confirming meeting details
5. Requesting changes to existing selections

CRITICAL RESCHEDULE HANDLING:
- If user requests a new date (August 30th, tomorrow, etc.), set next_step to "check_new_date" 
- Extract the new requested date and store it
- DO NOT assume any time slots - availability must be checked first
- Ask them to wait while you check availability for the new date
 
RESPOND WITH VALID JSON ONLY:
{{
    "action": "reschedule_request|partial_details|complete_details|need_more_info|error",
    "requested_new_date": "YYYY-MM-DD or relative date like 'August 30th'",
    "selected_slot": {{
        "date": "YYYY-MM-DD",
        "start_time": "HH:MM",
        "end_time": "HH:MM",
        "duration_minutes": 30
    }},
    "meeting_title": "Brief meeting title",
    "meeting_agenda": "Full agenda/topic description",
    "meeting_format": "virtual|in-person",
    "selected_room": {{
        "cabin_id": "room_id",
        "location": "location_name",
        "capacity": 0,
        "floor": 0
    }},
    "confidence": 0.95,
    "missing_details": ["slot", "agenda", "format"],
    "response_message": "Natural response to user about what was processed and what's needed next",
    "ready_for_confirmation": false,
    "next_step": "check_new_date|get_more_details|confirm_meeting|send_invites"
}}
 
RULES:
- If user mentions a new date, set action to "reschedule_request" and next_step to "check_new_date"
- For reschedule requests, respond with: "Let me check availability for [new date]. Please wait..."
- PRESERVE existing details unless user explicitly wants to change them
- Generate concise meeting titles from agenda (max 5 words)
- If user specifies physical room, set meeting_format to "in-person"
- Set ready_for_confirmation=true only when ALL required details are complete
- Be conversational and helpful in response_message
"""
 
    try:
        llm_response = await llm.ainvoke([
            SystemMessage(content=llm_prompt),
            HumanMessage(content=str(user_input))
        ])
       
        try:
            parsed_response = json.loads(llm_response.content.strip())
        except JSONDecodeError:
            # Clean up response and try again
            cleaned_content = llm_response.content.strip()
            if cleaned_content.startswith("```"):
                cleaned_content = cleaned_content.split("```")[-2] if cleaned_content.count("```") >= 2 else cleaned_content
                cleaned_content = cleaned_content.replace("json", "").strip()
            parsed_response = json.loads(cleaned_content)
       
        # Process LLM response
        action = parsed_response.get("action", "need_more_info")
        confidence = parsed_response.get("confidence", 0.0)
        next_step = parsed_response.get("next_step", "get_more_details")
        
        # Handle reschedule request
        if action == "reschedule_request" or next_step == "check_new_date":
            new_date = parsed_response.get("requested_new_date")
            if new_date:
                # Update the meeting request with new date
                state["meeting_request"]["requested_date"] = new_date
                
                # Clear previous availability data since we're checking a new date
                state["available_slots"] = []
                state["unavailable_attendees"] = []
                
                # Set response message
                response_message = f"Let me check availability for {new_date}. Please wait..."
                state["messages"].append({"content": response_message, "type": "system"})
                
                # Go back to check availability for the new date
                state["current_step"] = "check_availability"
                return state
        
        # Update state with extracted details (only if new or changed)
        if parsed_response.get("selected_slot") and confidence > 0.7:
            state["selected_slot"] = parsed_response["selected_slot"]
       
        if parsed_response.get("meeting_title"):
            state["meeting_title"] = parsed_response["meeting_title"]
           
        if parsed_response.get("meeting_agenda"):
            state["meeting_agenda"] = parsed_response["meeting_agenda"]
            state["meeting_description"] = f" {parsed_response['meeting_agenda']}"
       
        if parsed_response.get("meeting_format"):
            state["meeting_format"] = parsed_response["meeting_format"]
           
        if parsed_response.get("selected_room"):
            state["meeting_room"] = parsed_response["selected_room"]
            # Automatically set format to in-person if room is selected
            if not state.get("meeting_format"):
                state["meeting_format"] = "in-person"
       
        # Determine next step based on completeness
        ready_for_confirmation = parsed_response.get("ready_for_confirmation", False)
        response_message = parsed_response.get("response_message", "Let me process your request...")
       
        # Handle different next steps
        if ready_for_confirmation or next_step == "send_invites":
            # All details complete, move to sending invites
            state["confirmation_status"] = True
            state["current_step"] = "send_invites"
           
            # Add confirmation summary
            meeting_title = state.get("meeting_title", "Meeting")
            selected_slot = state.get("selected_slot", {})
            meeting_format = state.get("meeting_format", "virtual")
            meeting_room = state.get("meeting_room", {})
           
            date_str = selected_slot.get("date", "TBD")
            time_str = f"{selected_slot.get('start_time', 'TBD')} - {selected_slot.get('end_time', 'TBD')}"
            
            location_str = meeting_room.get("cabin_id", "Online") if meeting_format == "in-person" else "Virtual"
            print("***====Meeting room: ", location_str)
            attendee_names = [att.get("name") for att in attendees]
           
            confirmation_summary = f"""✅ Meeting confirmed! Here are the details:
 
📋 **{meeting_title}**
📅 Date: {date_str}
🕒 Time: {time_str}
👥 Attendees: {', '.join(attendee_names)}
📍 Location: {location_str}
📝 Agenda: {state.get('meeting_agenda', 'TBD')}
 
Sending calendar invites now..."""
           
            state["messages"].append({"content": confirmation_summary, "type": "system"})
           
        elif next_step == "confirm_meeting":
            # Ready for final confirmation
            state["current_step"] = "human_meeting_details"
           
            # Show summary for confirmation
            summary = f"""Please confirm these meeting details:
           
Meeting: {state.get('meeting_title', 'TBD')}
Date & Time: {state.get('selected_slot', {}).get('date', 'TBD')} at {state.get('selected_slot', {}).get('start_time', 'TBD')}
Format: {state.get('meeting_format', 'TBD')}
Agenda: {state.get('meeting_agenda', 'TBD')}
 
Type 'confirm' to send invites or let me know if you'd like to change anything."""
           
            state["messages"].append({"content": summary, "type": "system"})
            state["human_node_conv"].append({"System": summary})
           
        else:
            # Need more details, stay in this node
            state["current_step"] = "human_meeting_details"
            state["messages"].append({"content": response_message, "type": "system"})
            state["human_node_conv"].append({"System": response_message})
       
        return state
       
    except Exception as e:
        print(f"Error in LLM meeting details processing: {e}")
       
        # Fallback: ask for more details
        state["current_step"] = "human_meeting_details"
        fallback_message = "I need more information. Please provide the missing details."
        state["messages"].append({
            "content": fallback_message,
            "type": "system"
        })
        state["human_node_conv"].append({"System": fallback_message})
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
    slot["duration_hours"] = slot["duration_minutes"]/ 60  # Convert minutes to hours
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
        "time": f"{slot["start_time"]} - {slot["end_time"]}",
        "duration_minutes": slot["duration_minutes"],
        "attendee_emails": [a["email"] for a in state["attendees"]],
        "location": 
        f"Floor: {state['meeting_room']['floor']}, Cabin Id: {state['meeting_room']['cabin_id']}, Capacity: {state['meeting_room']['capacity']}" if state.get("meeting_room") else "Online",
        "description": state.get("meeting_description", "")
    }
    print(f"====Meeting Room inside send invite: {state['meeting_room']}====\n")
    state["messages"].append(tool_call_message)
    tool_call_message_json = json.loads(tool_call_message)
    if tool_call_message_json.get("emails_sent", False):
        formatted_details = format_meeting_details(state['meeting_details'])
        state["messages"].append(AIMessage(content=f"✅ Invites sent successfully!<br><br>{formatted_details}"))
    state["current_step"] = "complete"
    
    return state

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

# Updated routing function for the simplified workflow
def route_conversation(state: SchedulingState) -> str:
    """Route to the appropriate node based on current state"""
    
    current_step = state.get("current_step", "parse_request")
    
    if current_step == "parse_request":
        return "parse_request"
    elif current_step == "check_availability":
        return "check_availability"
    elif current_step == "human_meeting_details":
        return "human_meeting_details"  # Single interrupt point
    elif current_step == "send_invites":
        return "send_invites"
    elif current_step == "complete":
        return "END"
    # Add handling for reschedule case
    elif current_step == "reschedule" or current_step == "gather_more_info":
        return "human_meeting_details"  # Route to human intervention for rescheduling
    else:
        return "parse_request"