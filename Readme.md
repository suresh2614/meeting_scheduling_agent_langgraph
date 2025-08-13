# Executive Meeting Scheduler - LangGraph Implementation

A production-ready meeting scheduler built with LangGraph, featuring WebSocket support and your exact conversational prompts.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Up Environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Set Up Database
```bash
# Using Docker
docker-compose up postgres -d

# Or manually
createdb meeting_scheduler
psql meeting_scheduler < init_db.sql
```

### 4. Run the Application
```bash
python api.py
```

The application will be available at http://localhost:8001

## 📁 Project Structure

```
Backend/
├── agents.py           # Main LangGraph agent
├── api.py             # FastAPI with WebSocket support
├── calendar_tools.py  # Your existing calendar integration
├── config.py          # Configuration management
├── graph.py           # LangGraph workflow definition
├── knowledge.py       # Knowledge base for availability
├── meeting_rooms.py   # Meeting room management
├── nodes.py           # Workflow nodes
├── prompts.py         # Your exact system prompts
├── state.py           # State definitions
├── tools.py           # Calendar tool wrapper
└── users_availability.json  # User availability data
```

## 🔧 Features

- **LangGraph v0.2+** - Latest patterns, no deprecated memory
- **WebSocket Support** - Real-time conversations
- **Your Exact Prompts** - All your business rules preserved
- **Meeting Room Logic** - NYC, Chicago, SF offices with capacity-based selection
- **State Persistence** - PostgreSQL checkpointing
- **Production Ready** - Error handling, logging, Docker support

## 💬 Example Usage

### REST API (Backward Compatible)
```bash
curl -X POST http://localhost:8001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Schedule a meeting with John and Sarah"}'
```

### WebSocket (Recommended)
```javascript
const ws = new WebSocket('ws://localhost:8001/ws/chat/session-123');

ws.onmessage = (event) => {
    console.log('Agent:', event.data);
};

ws.send('Schedule a meeting with John and Sarah tomorrow at 2pm');
```

## 🐳 Docker Deployment

```bash
docker-compose up
```

## 📊 Architecture

```
User → WebSocket → FastAPI → LangGraph Agent → Calendar Tools
                                ↓
                        Knowledge Base (pgvector)
                                ↓
                        State Persistence (PostgreSQL)
```

## 🔍 Key Improvements

1. **No Deprecated Patterns** - Uses latest LangGraph StateGraph
2. **Type Safety** - Full TypedDict state definitions  
3. **Checkpointing** - Conversation persistence across sessions
4. **Your Prompts** - Exact system prompt with all your rules
5. **Room Selection** - Smart cabin selection based on capacity
6. **WebSocket** - Real-time bidirectional communication

## 🧪 Testing

```python
# Test the agent
import asyncio
from agents import scheduler_agent

async def test():
    await scheduler_agent.initialize()
    response = await scheduler_agent.process_message(
        "Schedule a meeting with John",
        "test-session",
        "test-user",
        "test@email.com"
    )
    print(response)

asyncio.run(test())
```

## 📝 Notes

- Keep your existing `calendar_tools.py` file
- Keep your `users_availability.json` file  
- The system uses your exact prompts from `prompts.txt`
- All office locations (NYC, Chicago, SF) are configured
- WebSocket provides better UX than REST API
