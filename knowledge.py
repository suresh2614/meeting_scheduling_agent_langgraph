"""Simplified availability data management"""

import json
from typing import List, Dict, Any

class AvailabilityKnowledge:
    """Manages user availability knowledge base"""
    
    def __init__(self):
        self.availability_data = None
    
    async def initialize(self):
        """Initialize the knowledge base"""
        # Load availability data
        self.availability_data = self._load_availability_data()
    
    def _load_availability_data(self) -> Dict[str, Any]:
        """Load availability data from JSON file"""
        availability_file = "Backend/users_availability.json"
        
        try:
            with open(availability_file, 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            print(f"Availability file {availability_file} not found")
            return {"users": [], "locations": {}}
    
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