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
    
    # Build appropriate message based on context
    if is_followup and last_system_message:
        # This is a follow-up, use the last system message as context
        interrupt_data = {"message": last_system_message}
        print(f"Using follow-up message: {last_system_message}")
    else:
        # This is initial request, build comprehensive message
        message_lines = []
     
        # 1. Participants
        message_lines.append("1. Can you please confirm these are the correct participants:<br>")
        for name, email in zip(attendee_names, attendee_emails):
            message_lines.append(f"&nbsp;&nbsp;* {name} ({email})<br>")
     
        # 2. Check for past date or available slots
        llm_analysis = state.get("llm_analysis", {})
        if llm_analysis.get("status") == "invalid_past_date":
            # Handle past date scenario
            message_lines.append("<br>2. The requested date and time is in the past. Meetings cannot be scheduled for past dates. Please provide a current or future date.<br>")
        elif available_slots:
            unavailable = llm_analysis.get("unavailable_attendees")
            slots_text = "\n".join(
                [f"&nbsp;* {slot['start_time']} - {slot['end_time']} ET<br>" for slot in available_slots]
            )
            if unavailable:
                names = [entry['name'].capitalize() for entry in unavailable]
                if len(names) == 1:
                    unavailable_text = f"{names[0]} is unavailable for the requested slot. Please select any of the below available slots:<br><br>"
                else:
                    unavailable_text = f"{', '.join(names)} are unavailable for the requested slot. Please select any of the below available slots:<br><br> ."
                message_lines.append(
                    f"<br>2. {unavailable_text} {available_slots[0]['date']}:<br>{slots_text}<br>"
                )
            else:
                message_lines.append(
                    f"<br>2. Here are the available time slots for {available_slots[0]['date']}:<br>{slots_text}<br>"
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
    state["human_node_conv"].append({"User": user_input})
    
    # Build conversation context for LLM
    conversation_context = ""
    if state.get("human_node_conv"):
        conversation_context = "\n".join(
            f"{list(entry.keys())[0]}: {list(entry.values())[0]}"
            for entry in state["human_node_conv"]
        )
    
    # Enhanced LLM prompt that considers existing details
    llm_prompt = f"""
You are an AI meeting scheduler processing user input to finalize meeting details.
 
CONTEXT:
Available time slots: {json.dumps(available_slots, indent=2)}
Attendees: {[att.get('name') for att in attendees]}
Attendee locations: {json.dumps(attendee_locations, indent=2)}
Same location: {same_location}
Available rooms: {json.dumps(available_rooms, indent=2)}
Room options by location: {json.dumps(room_options_by_location, indent=2)}
LLM Analysis Status: {llm_analysis.get('status', 'unknown')}

EXISTING MEETING DETAILS:
- Selected slot: {existing_details.get('selected_slot', 'Not set')}
- Meeting title: {existing_details.get('meeting_title', 'Not set')}
- Meeting agenda: {existing_details.get('meeting_agenda', 'Not set')}
- Meeting format: {existing_details.get('meeting_format', 'Not set')}
- Meeting room: {existing_details.get('meeting_room', 'Not set')}

CONVERSATION HISTORY: 
{conversation_context}

CURRENT USER INPUT: "{user_input}"
 
TASK: Analyze the user input considering the conversation context and existing details. The user might:
1. Answer a specific follow-up question (agenda, format preference, confirmation)
2. Select a time slot
3. Provide meeting topic/agenda
4. Provide a new date (especially if previous was in the past)
5. Confirm meeting details
6. Request changes to existing selections
 
RESPOND WITH VALID JSON ONLY:
{{
    "action": "partial_details|complete_details|need_more_info|error|new_date_provided",
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
    "new_requested_date": "YYYY-MM-DD (if user provided a new date)",
    "confidence": 0.95,
    "missing_details": ["slot", "agenda", "format"],
    "response_message": "Natural response to user about what was processed and what's needed next",
    "ready_for_confirmation": false,
    "next_step": "get_more_details|confirm_meeting|send_invites|recheck_availability"
}}
 
RULES:
- If user provides a new date (after being told previous was in past), set action to "new_date_provided" and next_step to "recheck_availability"
- PRESERVE existing details unless user explicitly wants to change them
- If user provides a new slot, update selected_slot
- If user provides a new title, update meeting_title
- If user provides a new agenda, update meeting_agenda
- If user provides a new format, update meeting_format
- If user selects a room, update selected_room and set meeting_format to "in-person" if not already set
- If user provides only agenda when slot is already selected, don't reset the slot
- If the user insists on a specific date or time that is not available, go ahead and schedule it but inform them of the unavailability.Schedule it even if its in ooo, travel dates, weekends, Out of business hours .
- For the given agenda, generate a concise meeting_agenda 
- Generate a concise meeting title from the agenda (max 5 words)
- CRITICAL: If user specifies a physical room (mentions Floor, Cabin ID, room number, etc.), automatically set meeting_format to "in-person" - DO NOT ask for format confirmation
- If user says "virtual" or mentions online/video call, set meeting_format to "virtual"
- If different locations, recommend virtual but allow in-person with multiple rooms
- Set ready_for_confirmation=true only when ALL required details are complete
- Be conversational and helpful in response_message
- If user says "confirm" or similar, proceed to send invites
- Focus response on what the user just provided, not everything from scratch
- When a room is selected, acknowledge it and move on to other missing details (time/agenda) without asking about format
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
        
        # Handle new date provided after past date error
        if action == "new_date_provided" or next_step == "recheck_availability":
            new_date = parsed_response.get("new_requested_date")
            if new_date:
                # Update the meeting request with new date and go back to availability check
                state["meeting_request"]["requested_date"] = new_date
                state["current_step"] = "check_availability"
                
                response_message = parsed_response.get("response_message", f"Thank you for providing a new date ({new_date}). Let me check availability again.")
                state["messages"].append({"content": response_message, "type": "system"})
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