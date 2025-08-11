from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
import os
import uuid
import jwt
from agents import scheduler_agent
from config import settings
from contextlib import asynccontextmanager
from langgraph.types import Command
from langchain.schema import SystemMessage, HumanMessage, AIMessage
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
from langgraph.types import Command
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# Models
class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    response: str
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# FastAPI app
app = FastAPI(title="Executive Meeting Scheduler API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Security
security = HTTPBearer()

class SessionManager:
    """Manage user sessions"""
    
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def create_session(self, user_id: str, user_name: str) -> str:
        """Create a new session"""
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "user_id": user_id,
            "user_name": user_name,
            "created_at": datetime.now(),
            "last_activity": datetime.now()
        }
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        return self.sessions.get(session_id)
    
    def update_activity(self, session_id: str):
        """Update last activity time"""
        if session_id in self.sessions:
            self.sessions[session_id]["last_activity"] = datetime.now()
    
    def cleanup_sessions(self):
        """Remove expired sessions"""
        expired_time = datetime.now() - timedelta(hours=2)
        expired_sessions = [
            sid for sid, data in self.sessions.items()
            if data["last_activity"] < expired_time
        ]
        for sid in expired_sessions:
            del self.sessions[sid]

session_manager = SessionManager()

# In-memory session tracking for backward compatibility
user_session_id = {}

# Authentication (optional)
def verify_token_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """Optionally verify JWT token"""
    if not credentials:
        return None
    
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except:
        return None


# Lifespan event handler for FastAPI (replaces deprecated @app.on_event("startup"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await scheduler_agent.initialize()
    logger.info("Meeting Scheduler Agent initialized")
    yield

# Re-create app with lifespan handler
app = FastAPI(title="Executive Meeting Scheduler API", version="2.0.0", lifespan=lifespan)

@app.get("/")
async def root():
    """Redirect to home"""
    return RedirectResponse(url="/home")

@app.get("/home", response_class=HTMLResponse)
async def home():
    """Serve frontend HTML for WebSocket chat"""
    html_file = Path("static/ws_chat.html")
    if html_file.exists():
        return HTMLResponse(html_file.read_text(), status_code=200)
    return HTMLResponse("<h1>Meeting Scheduler UI Not Found</h1>", status_code=404)

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """REST endpoint for chat (backward compatibility)"""
    global user_session_id
    
    try:
        logger.info(f"User question: {req.question}")
        
        # Simple session management
        user_name = "john@gmail.com"  # Default user
        
        if req.question.strip().lower() == "hi":
            session_id = str(uuid.uuid4())
            user_session_id[user_name] = session_id
            logger.info(f"New session_id generated: {session_id}")
        else:
            session_id = user_session_id.get(user_name)
            if not session_id:
                session_id = str(uuid.uuid4())
                user_session_id[user_name] = session_id
                logger.info(f"New session_id generated: {session_id}")
            else:
                logger.info(f"Using existing session_id: {session_id}")
        
        # Process message
        response = await scheduler_agent.process_message(
            message=req.question,
            session_id=session_id,
            user_id="johnDeo123",
            user_name=user_name
        )
        
        logger.info(f"Agent Response: {response}")
        
        return ChatResponse(response=response)
        
    except Exception as e:
        logger.exception("Chat processing failed")
        raise HTTPException(status_code=500, detail=str(e))
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
                SystemMessage(content=scheduler_agent.system_prompt),
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
        stream = scheduler_agent.graph.astream(initial_state, config=config_thread)

        while True:
            try:
                async for chunk in stream:
                    for node_id, value in chunk.items():
                        if node_id == "__interrupt__":
                            interrupt_info = value[0].value
                            message_text = interrupt_info.get('message', 'Please provide input: ')

                            await websocket.send_json({
                                "type": "question",
                                "message": message_text
                            })

                            user_response = await websocket.receive_json()
                            user_input = user_response.get("message", "")

                            await scheduler_agent.graph.ainvoke(
                                Command(resume=user_input),
                                config=config_thread
                            )

                            stream = scheduler_agent.graph.astream(None, config=config_thread)
                            break

                        elif node_id == "calendar_event":
                            await websocket.send_json({
                                "type": "complete",
                                "message": "Meeting scheduled successfully!",
                                "meeting_details": value
                            })
                            return "Meeting scheduled successfully!"

                        else:
                            await websocket.send_json({
                                "type": "progress",
                                "message": f"Processing node: {node_id}"
                            })

                current_state = scheduler_agent.graph.get_state(config_thread)
                if current_state.next == ():
                    break
                else:
                    stream = scheduler_agent.graph.astream(None, config=config_thread)

            except StopAsyncIteration:
                current_state = scheduler_agent.graph.get_state(config_thread)
                if current_state.next == ():
                    break
                else:
                    stream = scheduler_agent.graph.astream(None, config=config_thread)

        # Final message from AI if available
        final_state = scheduler_agent.graph.get_state(config_thread)
        if final_state and final_state.values:
            ai_messages = [
                msg for msg in final_state.values.get("messages", [])
                if isinstance(msg, AIMessage)
            ]
            if ai_messages:
                last_message = ai_messages[-1].content
                await websocket.send_json({
                    "type": "final_message",
                    "message": last_message
                })
                return last_message
            else:
                await websocket.send_json({
                    "type": "complete",
                    "message": "Workflow completed successfully."
                })
                return "Workflow completed successfully."
        else:
            await websocket.send_json({
                "type": "complete",
                "message": "Workflow completed, but no final message found."
            })
            return "No final message found."

    except WebSocketDisconnect:
        print(f"Client {session_id} disconnected")
    except Exception as e:
        print(f"Error in WebSocket connection {session_id}: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"An error occurred: {str(e)}"
        })
        return f"Error: {str(e)}"
    finally:
        if session_id in active_connections:
            del active_connections[session_id]

@app.websocket("/ws/chat/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time chat"""
    await websocket.accept()
    
    # Get session or create new one
    session = session_manager.get_session(session_id)
    if not session:
        # For demo, create session without auth
        session = {
            "user_id": "demo_user",
            "user_name": "demo@example.com"
        }
        session_manager.sessions[session_id] = session
    
    try:
        # Send greeting
        await websocket.send_text("Hello! I'm your meeting scheduler. How can I help you today?")
        
        while True:
            # Receive message
            message = await websocket.receive_text()
            
            if message.lower() in ['exit', 'quit', 'bye']:
                await websocket.send_text("Thank you. Have a great day!")
                break
            
            # Process message
            response = await scheduler_agent.process_message(
                message=message,
                session_id=session_id,
                user_id=session["user_id"],
                user_name=session["user_name"]
            )
            
            # Send response
            await websocket.send_text(response)
            
            # Update activity
            session_manager.update_activity(session_id)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")

@app.get("/api/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    }

# Main
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_level="info"
    )