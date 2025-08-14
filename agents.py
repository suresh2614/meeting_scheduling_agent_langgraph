"""LangGraph-based meeting scheduler agent"""

from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from graph import create_graph
from state import SchedulingState
from knowledge import AvailabilityKnowledge
from prompts import get_system_prompt
import logging
from langgraph.types import Command
from fastapi import WebSocket, WebSocketDisconnect
logger = logging.getLogger(__name__)

class MeetingSchedulerAgent:
    """Main agent class for meeting scheduling"""
    
    def __init__(self):
        self.graph = None
        self.knowledge = AvailabilityKnowledge()
        self.system_prompt = get_system_prompt()  # Use your exact prompt
    
    async def initialize(self):
        """Initialize the agent"""
        # Initialize knowledge base
        await self.knowledge.initialize()
        
        # Create graph
        self.graph = await create_graph()
    active_connections = {}
    async def process_message(self,websocket: WebSocket,
        message: str,
        session_id: str,
        user_id: str,
        user_name: str
    ) -> str:
        await websocket.accept()
        self.active_connections[session_id] = websocket

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

            config_thread = {"configurable": {"thread_id": session_id}}
            stream = self.graph.astream(initial_state, config=config_thread)

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
                                await self.graph.ainvoke(
                                    Command(resume=user_input),
                                    config=config_thread
                                )

                                stream = self.graph.astream(None, config=config_thread)
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

                    current_state = self.graph.get_state(config_thread)
                    if current_state.next == ():
                        break
                    else:
                        stream = self.graph.astream(None, config=config_thread)

                except StopAsyncIteration:
                    current_state = self.graph.get_state(config_thread)
                    if current_state.next == ():
                        break
                    else:
                        stream = self.graph.astream(None, config=config_thread)

            # Final message from AI if available
            final_state = self.graph.get_state(config_thread)
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
            if session_id in self.active_connections:
                del self.active_connections[session_id]

# Global agent instance
scheduler_agent = MeetingSchedulerAgent()
