"""LangGraph workflow definition with corrected human interrupts"""

from langgraph.graph import StateGraph, END

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from typing import Dict, Any
from state import SchedulingState
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

import json
from nodes import *

from Backend.calendar_tools import create_calendar_event
from config import settings
import asyncpg
llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0.1,
    api_key=settings.openai_api_key
)


# Updated graph creation function
async def create_graph():
    """Create the simplified scheduling workflow graph with single human interrupt"""
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    
    # Create workflow
    workflow = StateGraph(SchedulingState)
    
    # Add simplified nodes
    workflow.add_node("parse_request", parse_request_node)
    workflow.add_node("check_availability", check_availability_node)
    workflow.add_node("human_meeting_details", human_meeting_details_node)  # Consolidated node
    workflow.add_node("send_invites", send_invites_node)
    
    # Add conditional routing
    workflow.add_conditional_edges("parse_request", route_conversation)
    workflow.add_conditional_edges("check_availability", route_conversation)
    workflow.add_conditional_edges("human_meeting_details", route_conversation)
    
    # Final execution flow
    workflow.add_edge("send_invites", END)
    
    # Set entry point
    workflow.set_entry_point("parse_request")
    
    # Create checkpointer for persistence (required for interrupts)
    checkpointer = MemorySaver()
    
    # Compile with checkpointer and interrupt support
    graph = workflow.compile(checkpointer=checkpointer)
    
    return graph