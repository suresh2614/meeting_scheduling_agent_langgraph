"""Knowledge base management for availability data"""

import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncpg
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import PGVector
from langchain.schema import Document
from config import settings

class AvailabilityKnowledge:
    """Manages user availability knowledge base"""
    
    def __init__(self):
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=settings.gemini_api_key
        )
        self.vector_store = None
        self.availability_data = None
        
    async def initialize(self):
        """Initialize the knowledge base"""
        # Load availability data
        self.availability_data = self._load_availability_data()
        
        # Create vector store
        self.vector_store = PGVector(
            embedding_function=self.embeddings,
            collection_name="availability_knowledge_langraph",
            connection_string=settings.database_url,
        )
        
        # Add documents
        documents = self._create_documents()
        if documents:
            await self.vector_store.aadd_documents(documents)
    
    def _load_availability_data(self) -> Dict[str, Any]:
        """Load availability data from JSON file"""
        availability_file = "Backend/users_availability.json"
        
        try:
            with open(availability_file, 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            print(f"Availability file {availability_file} not found")
            return {"users": [], "locations": {}}
    
    def _create_documents(self) -> List[Document]:
        """Create document objects for vector store"""
        documents = []
        
        # Process user availability
        for user in self.availability_data.get("users", []):
            user_doc_content = self._create_user_document(user)
            documents.append(Document(
                page_content=user_doc_content,
                metadata={
                    "type": "user_availability",
                    "user_email": user['email'],
                    "user_name": user['name']
                }
            ))
        
        # Process locations
        locations_doc_content = self._create_locations_document()
        documents.append(Document(
            page_content=locations_doc_content,
            metadata={"type": "office_locations"}
        ))
        
        # Create summary documents
        summary_doc_content = self._create_availability_summary()
        documents.append(Document(
            page_content=summary_doc_content,
            metadata={"type": "availability_summary"}
        ))
        
        return documents
    
    def _create_user_document(self, user: Dict[str, Any]) -> str:
        """Create a document for a single user's availability"""
        doc = f"""
User Profile:
- Email: {user['email']}
- Name: {user['name']}
- Timezone: {user['timezone']}
- Base Location: {user.get('base_location', 'Not specified')}

Out of Office Dates: {', '.join(user.get('ooo_dates', [])) if user.get('ooo_dates') else 'None'}
Business Travel Dates: {', '.join(user.get('travel_dates', [])) if user.get('travel_dates') else 'None'}

Calendar Events:"""
        
        calendar_events = user.get("calendar_events", {})
        for date, events in calendar_events.items():
            doc += f"\n\nDate: {date}"
            for event in events:
                doc += f"\n  - Time: {event['slot']}"
                doc += f"\n    Event: {event['title']}"
                doc += f"\n    Event ID: {event['event_id']}"
        
        return doc
    
    def _create_locations_document(self) -> str:
        """Create a document for office locations"""
        doc = "Office Locations and Meeting Rooms:\n\n"
        
        locations = self.availability_data.get("locations", {})
        for location_name, location_data in locations.items():
            doc += f"Location: {location_name.title()}\n"
            floors = location_data.get("floors", {})
            for floor_name, floor_data in floors.items():
                doc += f"  {floor_name.replace('_', ' ').title()}:\n"
                cabins = floor_data.get("cabins", [])
                for cabin in cabins:
                    doc += f"    - Cabin ID: {cabin['cabin_id']}\n"
                    doc += f"      Capacity: {cabin['capacity']} people\n"
            doc += "---\n"
        
        return doc
    
    def _create_availability_summary(self) -> str:
        """Create a summary document of all unavailability"""
        doc = "User Unavailability Summary:\n\n"
        
        for user in self.availability_data.get("users", []):
            doc += f"User: {user['name']} ({user['email']})\n"
            doc += f"Timezone: {user['timezone']}\n"
            
            # Out of office dates
            ooo_dates = user.get('ooo_dates', [])
            travel_dates = user.get('travel_dates', [])
            
            if ooo_dates:
                doc += f"Out of Office: {', '.join(ooo_dates)}\n"
            
            if travel_dates:
                doc += f"On Business Travel: {', '.join(travel_dates)}\n"
            
            # Busy slots summary
            calendar_events = user.get("calendar_events", {})
            doc += "Busy days summary:\n"
            for date, events in calendar_events.items():
                doc += f"  {date}: {len(events)} meeting(s)\n"
            
            doc += "---\n"
        
        return doc
    
    async def search(self, query: str, k: int = 5) -> List[Document]:
        """Search the knowledge base"""
        if not self.vector_store:
            await self.initialize()
        
        return await self.vector_store.asimilarity_search(query, k=k)
    
    def get_user_availability(self, email: str) -> Optional[Dict[str, Any]]:
        """Get specific user's availability data"""
        for user in self.availability_data.get("users", []):
            if user['email'] == email:
                return user
        return None
    
    def get_available_rooms(self, location: str, capacity: int) -> List[Dict[str, Any]]:
        """Get available meeting rooms for a location"""
        rooms = []
        locations = self.availability_data.get("locations", {})
        
        location_data = locations.get(location.lower(), {})
        for floor_name, floor_data in location_data.get("floors", {}).items():
            for cabin in floor_data.get("cabins", []):
                if cabin['capacity'] >= capacity:
                    rooms.append({
                        "location": location,
                        "floor": floor_name,
                        "cabin_id": cabin['cabin_id'],
                        "capacity": cabin['capacity']
                    })
        
        return sorted(rooms, key=lambda x: x['capacity'])
    async def get_available_slots(self, attendees: List[str]) -> str:
        try:
            with open('Backend/users_availability.json', 'r') as f:
                USER_DATA = json.load(f)["users"]
        except FileNotFoundError:
            print("WARNING: Backend/users_availability.json not found. The availability checker will not work.")
            USER_DATA = []

        users_data = []
        for attendee_name in attendees:
            user = next((u for u in USER_DATA if u["name"].lower() == attendee_name.lower()), None)
            if user:
                users_data.append(user)

        return users_data