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


async def create_graph():
    """Create the scheduling workflow graph with human interrupts"""
    
    # Create workflow
    workflow = StateGraph(SchedulingState)
    
    # Add original nodes
    workflow.add_node("parse_request", parse_request_node)
    workflow.add_node("check_availability", check_availability_node)
    workflow.add_node("gather_details", gather_details_node)
    workflow.add_node("determine_format", determine_format_node)
    workflow.add_node("process_format_selection", process_format_selection_node)
    workflow.add_node("confirm_meeting", confirm_meeting_node)
    workflow.add_node("send_invites", send_invites_node)
    workflow.add_node("calendar_event", create_calendar_event)
    
    # Add human interrupt nodes
    workflow.add_node("human_time_selection", human_time_selection_node)
    workflow.add_node("human_format_selection", human_format_selection_node)
    workflow.add_node("human_agenda_input", human_agenda_input_node)
    workflow.add_node("human_confirmation", human_confirmation_node)
    
    # Add conditional routing with interrupts
    workflow.add_conditional_edges("parse_request", route_with_interrupts)
    workflow.add_conditional_edges("check_availability", route_with_interrupts)
    workflow.add_conditional_edges("gather_details", route_with_interrupts)
    workflow.add_conditional_edges("determine_format", route_with_interrupts)
    workflow.add_conditional_edges("process_format_selection", route_with_interrupts)
    workflow.add_conditional_edges("confirm_meeting", route_with_interrupts)
    
    # Human interrupt nodes continue based on their internal logic
    workflow.add_conditional_edges("human_time_selection", route_with_interrupts)
    workflow.add_conditional_edges("human_format_selection", route_with_interrupts)
    workflow.add_conditional_edges("human_agenda_input", route_with_interrupts)
    workflow.add_conditional_edges("human_confirmation", route_with_interrupts)
    
    # Final execution flow
    workflow.add_edge("send_invites", END)
    # workflow.add_edge("calendar_event", END)
    
    # Set entry point
    workflow.set_entry_point("parse_request")
    
    # Create checkpointer for persistence (required for interrupts)
    checkpointer = MemorySaver()
    
    # Compile with checkpointer and interrupt support
    graph = workflow.compile(checkpointer=checkpointer)
    
    return graph