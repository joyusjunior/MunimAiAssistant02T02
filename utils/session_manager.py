"""
Session management for Munim AI conversations.
This module tracks conversation context and supports multi-step workflows.
"""
import json
import logging
import time
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# In-memory session storage - in a production app, this would use a database
# Key is session_id, value is session data
SESSIONS = {}

# Define session timeout in seconds (30 min)
SESSION_TIMEOUT = 1800  

# Define session states for conversation flows
class SessionState:
    IDLE = "idle"                     # No active conversation flow
    INVOICE_CREATION = "invoice"      # Creating a new invoice
    EXPENSE_RECORDING = "expense"     # Recording an expense
    PAYMENT_RECORDING = "payment"     # Recording a payment
    LEDGER_MANAGEMENT = "ledger"      # Managing a ledger
    INVENTORY_MANAGEMENT = "inventory" # Managing inventory

def create_session():
    """Create a new session ID and initialize session data"""
    session_id = f"session_{int(time.time() * 1000)}"
    SESSIONS[session_id] = {
        "state": SessionState.IDLE,
        "data": {},
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    }
    return session_id

def get_session(session_id):
    """Get session data for a given session ID, or create a new session if invalid"""
    if not session_id or session_id not in SESSIONS:
        return None
    
    # Check if session has expired
    session = SESSIONS[session_id]
    last_updated = datetime.fromisoformat(session["last_updated"])
    now = datetime.now()
    time_diff = (now - last_updated).total_seconds()
    
    if time_diff > SESSION_TIMEOUT:
        # Session expired, clean it up
        del SESSIONS[session_id]
        return None
    
    # Update the last_updated timestamp
    session["last_updated"] = now.isoformat()
    SESSIONS[session_id] = session
    
    return session

def update_session(session_id, state=None, data=None):
    """Update session state and/or data"""
    if not session_id or session_id not in SESSIONS:
        return False
    
    session = SESSIONS[session_id]
    
    if state:
        session["state"] = state
    
    if data:
        # Merge new data with existing data
        session["data"].update(data)
    
    session["last_updated"] = datetime.now().isoformat()
    SESSIONS[session_id] = session
    
    return True

def get_all_sessions():
    """Get all active sessions"""
    return SESSIONS

def get_session_data(session_id, key=None):
    """Get session data for a specific key or all data if key is None"""
    session = get_session(session_id)
    if not session:
        return None
    
    if key:
        return session["data"].get(key)
    
    return session["data"]

def clear_session_data(session_id):
    """Clear all data for a session but maintain the session"""
    if not session_id or session_id not in SESSIONS:
        return False
    
    session = SESSIONS[session_id]
    session["data"] = {}
    session["last_updated"] = datetime.now().isoformat()
    SESSIONS[session_id] = session
    
    return True

def end_session(session_id):
    """End a session completely by removing it"""
    if not session_id or session_id not in SESSIONS:
        return False
    
    del SESSIONS[session_id]
    return True

def clean_expired_sessions():
    """Clean up expired sessions"""
    now = datetime.now()
    expired_sessions = []
    
    for session_id, session in SESSIONS.items():
        last_updated = datetime.fromisoformat(session["last_updated"])
        time_diff = (now - last_updated).total_seconds()
        
        if time_diff > SESSION_TIMEOUT:
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        del SESSIONS[session_id]
    
    return len(expired_sessions)