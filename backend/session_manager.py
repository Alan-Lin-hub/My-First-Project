from typing import List, Optional
from collections import OrderedDict
from dataclasses import dataclass

@dataclass
class Message:
    """Represents a single message in a conversation"""
    role: str     # "user" or "assistant"
    content: str  # The message content

class SessionManager:
    """Manages conversation sessions and message history.

    Sessions live in memory only. To stop unbounded growth (sessions are never
    explicitly closed), at most `max_sessions` are retained: the least recently
    used one is evicted when the cap is exceeded. An evicted session simply loses
    its history — the next query under that id starts fresh.
    """

    def __init__(self, max_history: int = 5, max_sessions: int = 1000):
        self.max_history = max_history
        self.max_sessions = max_sessions
        self.sessions: "OrderedDict[str, List[Message]]" = OrderedDict()
        self.session_counter = 0

    def _touch(self, session_id: str):
        """Mark a session as most-recently-used."""
        self.sessions.move_to_end(session_id)

    def _evict_if_needed(self):
        """Drop the least-recently-used sessions over the cap."""
        while len(self.sessions) > self.max_sessions:
            self.sessions.popitem(last=False)

    def create_session(self) -> str:
        """Create a new conversation session"""
        self.session_counter += 1
        session_id = f"session_{self.session_counter}"
        self.sessions[session_id] = []
        self._evict_if_needed()
        return session_id

    def add_message(self, session_id: str, role: str, content: str):
        """Add a message to the conversation history"""
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self._touch(session_id)
        self._evict_if_needed()

        message = Message(role=role, content=content)
        self.sessions[session_id].append(message)

        # Keep conversation history within limits
        if len(self.sessions[session_id]) > self.max_history * 2:
            self.sessions[session_id] = self.sessions[session_id][-self.max_history * 2:]
    
    def add_exchange(self, session_id: str, user_message: str, assistant_message: str):
        """Add a complete question-answer exchange"""
        self.add_message(session_id, "user", user_message)
        self.add_message(session_id, "assistant", assistant_message)
    
    def get_conversation_history(self, session_id: Optional[str]) -> Optional[str]:
        """Get formatted conversation history for a session"""
        if not session_id or session_id not in self.sessions:
            return None
        
        messages = self.sessions[session_id]
        if not messages:
            return None
        
        # Format messages for context
        formatted_messages = []
        for msg in messages:
            formatted_messages.append(f"{msg.role.title()}: {msg.content}")
        
        return "\n".join(formatted_messages)
    
    def clear_session(self, session_id: str):
        """Clear all messages from a session"""
        if session_id in self.sessions:
            self.sessions[session_id] = []