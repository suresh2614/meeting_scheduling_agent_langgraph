from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
from langgraph.types import Command
from langchain.schema import SystemMessage, HumanMessage, AIMessage

# Keep track of active WebSocket connections
active_connections = {}

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections[session_id] = websocket

    try:
        await websocket.send_json({
            "type": "connected",
            "message": "Connected! Please describe the meeting you'd like to schedule."
        })

        # Receive initial message
        data = await websocket.receive_json()
        message = data.get("message", "")
        user_id = data.get("user_id", "unknown_user")
        user_name = data.get("user_name", "Anonymous")

        # Construct initial state
        initial_state = {
            "messages": [
                SystemMessage(content=YOUR_CLASS_INSTANCE.system_prompt),
                HumanMessage(content=message)
            ],
            "session_id": session_id,
            "user_id": user_id,
            "user_name": user_name,
            "current_step": "parse_request",
            "meeting_request": {},
            "attendees": [],
            "available_slots": [],
            "selected_slot": None,
            "meeting_title": None,
            "meeting_description": None,
            "meeting_agenda": None,
            "meeting_format": None,
            "meeting_room": None,
            "available_rooms": None,
            "attendee_locations": None,
            "same_location": None,
            "confirmation_status": None,
            "error": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }

        config_thread = {"configurable": {"thread_id": session_id}}
        stream = YOUR_CLASS_INSTANCE.graph.astream(initial_state, config=config_thread)

        while True:
            try:
                async for chunk in stream:
                    for node_id, value in chunk.items():
                        if node_id == "__interrupt__":
                            interrupt_info = value[0].value
                            message_text = interrupt_info.get('message', 'Please provide input: ')

                            # Ask client for more input
                            await websocket.send_json({
                                "type": "question",
                                "message": message_text
                            })

                            user_response = await websocket.receive_json()
                            user_input = user_response.get("message", "")

                            # Resume with user input
                            await YOUR_CLASS_INSTANCE.graph.ainvoke(
                                Command(resume=user_input),
                                config=config_thread
                            )

                            stream = YOUR_CLASS_INSTANCE.graph.astream(None, config=config_thread)
                            break  # Break inner loop to restart stream

                        elif node_id == "calendar_event":
                            await websocket.send_json({
                                "type": "complete",
                                "message": "Meeting scheduled successfully!",
                                "meeting_details": value
                            })
                            return  # End the WebSocket session

                        else:
                            await websocket.send_json({
                                "type": "progress",
                                "message": f"Processing node: {node_id}"
                            })

                current_state = YOUR_CLASS_INSTANCE.graph.get_state(config_thread)
                if current_state.next == ():
                    break
                else:
                    stream = YOUR_CLASS_INSTANCE.graph.astream(None, config=config_thread)

            except StopAsyncIteration:
                current_state = YOUR_CLASS_INSTANCE.graph.get_state(config_thread)
                if current_state.next == ():
                    break
                else:
                    stream = YOUR_CLASS_INSTANCE.graph.astream(None, config=config_thread)

        # Final message from AI if available
        final_state = YOUR_CLASS_INSTANCE.graph.get_state(config_thread)
        if final_state and final_state.values:
            ai_messages = [
                msg for msg in final_state.values.get("messages", [])
                if isinstance(msg, AIMessage)
            ]
            if ai_messages:
                await websocket.send_json({
                    "type": "final_message",
                    "message": ai_messages[-1].content
                })
            else:
                await websocket.send_json({
                    "type": "complete",
                    "message": "Workflow completed successfully."
                })

    except WebSocketDisconnect:
        print(f"Client {session_id} disconnected")
    except Exception as e:
        print(f"Error in WebSocket connection {session_id}: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"An error occurred: {str(e)}"
        })
    finally:
        if session_id in active_connections:
            del active_connections[session_id]


#########################################################################################################################
async def process_message(
        self,
        message: str,
        session_id: str,
        user_id: str,
        user_name: str
    ) -> str:
        """Process a user message and return response"""
        try:
            # Create initial state
            initial_state = {
                "messages": [
                    SystemMessage(content=self.system_prompt),
                    HumanMessage(content=message)
                ],
                "session_id": session_id,
                "user_id": user_id,
                "user_name": user_name,
                "current_step": "parse_request",
                "meeting_request": {},
                "attendees": [],
                "available_slots": [],
                "selected_slot": None,
                "meeting_title": None,
                "meeting_description": None,
                "meeting_agenda": None,
                "meeting_format": None,
                "meeting_room": None,
                "available_rooms": None,
                "attendee_locations": None,
                "same_location": None,
                "confirmation_status": None,
                "error": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now()
            }
            # Run the graph
            config_thread = {"configurable": {"thread_id": session_id}}
        
            # Start initial stream
            stream = self.graph.astream(initial_state, config=config_thread)
            
            while True:
                try:
                    async for chunk in stream:
                        for node_id, value in chunk.items():
                            if node_id == "__interrupt__":
                                # Extract interrupt data properly
                                interrupt_info = value[0].value
                                message_text = interrupt_info.get('message', 'Please provide input: ')
                                
                                # Get user input
                                user_input = input(f"{message_text} ")
                                
                                # Resume with user input and get NEW stream
                                from langgraph.types import Command
                                await self.graph.ainvoke(Command(resume=user_input), config=config_thread)
                                
                                # Create a NEW stream after resuming
                                stream = self.graph.astream(None, config=config_thread)
                                break  # Break inner loop to start new stream iteration
                                
                            elif node_id == "calendar_event":
                                print("\n[COMPLETE] Meeting scheduled successfully!")
                                print("Final details:", value)
                                return {
                                    "status": "complete",
                                    "message": "Meeting scheduled successfully!",
                                    "meeting_details": value
                                }
                            else:
                                # Process other nodes
                                print(f"Processing node: {node_id}")
                                
                    # If we reach here without interrupts, check if workflow is complete
                    current_state = self.graph.get_state(config_thread)
                    if current_state.next == ():  # No more nodes to execute
                        break
                        
                except StopAsyncIteration:
                    # Stream ended, check if we need to continue
                    current_state = self.graph.get_state(config_thread)
                    if current_state.next == ():  # Workflow complete
                        break
                    # If there are still nodes to process, create new stream
                    stream = self.graph.astream(None, config=config_thread)
            
            # Get final state
            final_state = self.graph.get_state(config_thread)
            if final_state and final_state.values:
                ai_messages = [msg for msg in final_state.values.get("messages", [])
                            if isinstance(msg, AIMessage)]
                if ai_messages:
                    return ai_messages[-1].content
                    
            return "Workflow completed successfully."
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return f"I encountered an error: {str(e)}. Please try again."
