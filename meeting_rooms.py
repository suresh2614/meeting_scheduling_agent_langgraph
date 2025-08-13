"""Meeting room management"""

from typing import List, Dict, Optional

class MeetingRoomManager:
    """Manages meeting room availability and selection"""
    
    def __init__(self):
        self.rooms = {
            "new york": [
                {"floor": "1", "cabin_id": "M1C5", "capacity": 5},
                {"floor": "2", "cabin_id": "M2C3", "capacity": 3},
                {"floor": "2", "cabin_id": "M2C2", "capacity": 2}
            ],
            "chicago": [
                {"floor": "1", "cabin_id": "C1C5", "capacity": 5},
                {"floor": "2", "cabin_id": "C2C3", "capacity": 3},
                {"floor": "2", "cabin_id": "C2C2", "capacity": 2}
            ],
            "san francisco": [
                {"floor": "1", "cabin_id": "S1C5", "capacity": 5},
                {"floor": "2", "cabin_id": "S2C3", "capacity": 3},
                {"floor": "2", "cabin_id": "S2C2", "capacity": 2}
            ]
        }
    
    def get_available_rooms(self, location: str, num_attendees: int) -> List[Dict]:
        """Get available rooms for a location that can accommodate attendees"""
        location_lower = location.lower()
        
        if location_lower not in self.rooms:
            return []
        
        # Filter rooms by capacity
        suitable_rooms = [
            {
                "location": location,
                "floor": room["floor"],
                "cabin_id": room["cabin_id"],
                "capacity": room["capacity"]
            }
            for room in self.rooms[location_lower]
            if room["capacity"] >= num_attendees
        ]
        
        # Sort by capacity (prefer smaller rooms that fit)
        return sorted(suitable_rooms, key=lambda x: x["capacity"])[:2]  # Return top 2 options
    
    def get_rooms_for_multiple_locations(self, location_attendees: Dict[str, List[str]]) -> Dict[str, List[Dict]]:
        """Get room options for multiple locations"""
        room_options = {}
        
        for location, attendees in location_attendees.items():
            num_attendees = len(attendees)
            room_options[location] = self.get_available_rooms(location, num_attendees)
        
        return room_options








