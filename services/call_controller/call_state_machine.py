"""
Call State Machine for Asterisk AI Voice Agent v2.0

This module implements a comprehensive call state machine that manages
the lifecycle of voice calls through various states and transitions.
"""

import asyncio
import logging
from enum import Enum
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import uuid


logger = logging.getLogger(__name__)


class CallState(Enum):
    """Call states in the state machine"""
    
    # Initial states
    RINGING = "ringing"          # Call received, not yet answered
    ANSWERED = "answered"        # Call answered, RTP established
    
    # Active states
    LISTENING = "listening"      # Waiting for user speech
    SPEAKING = "speaking"        # AI is speaking
    PROCESSING = "processing"    # Processing user input (STT/LLM)
    
    # Control states
    BARGING_IN = "barging_in"    # User interrupting AI speech
    TRANSFERRING = "transferring" # Call being transferred
    
    # Final states
    ENDED = "ended"              # Call terminated
    TIMEOUT = "timeout"          # Call timed out
    ERROR = "error"              # Call ended due to error


@dataclass
class CallData:
    """Call data structure"""
    
    call_id: str
    channel_id: str
    state: CallState
    created_at: datetime
    updated_at: datetime
    
    # Caller information
    caller_id: Optional[str] = None
    caller_name: Optional[str] = None
    
    # Media information
    local_rtp_port: Optional[int] = None
    remote_rtp_port: Optional[int] = None
    local_rtcp_port: Optional[int] = None
    remote_rtcp_port: Optional[int] = None
    
    # Conversation data
    conversation_id: Optional[str] = None
    last_activity: Optional[datetime] = None
    
    # Error information
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.conversation_id is None:
            self.conversation_id = str(uuid.uuid4())


class CallStateMachine:
    """Call state machine with transition validation and event handling"""
    
    def __init__(self):
        self.calls: Dict[str, CallData] = {}
        self.state_handlers: Dict[CallState, List[Callable]] = {}
        self.transition_handlers: Dict[tuple, List[Callable]] = {}
        
        # Define valid state transitions
        self.valid_transitions = {
            CallState.RINGING: [CallState.ANSWERED, CallState.ENDED, CallState.ERROR],
            CallState.ANSWERED: [CallState.LISTENING, CallState.ENDED, CallState.ERROR],
            CallState.LISTENING: [CallState.PROCESSING, CallState.SPEAKING, CallState.ENDED, CallState.ERROR],
            CallState.PROCESSING: [CallState.SPEAKING, CallState.LISTENING, CallState.ENDED, CallState.ERROR],
            CallState.SPEAKING: [CallState.BARGING_IN, CallState.LISTENING, CallState.ENDED, CallState.ERROR],
            CallState.BARGING_IN: [CallState.LISTENING, CallState.ENDED, CallState.ERROR],
            CallState.TRANSFERRING: [CallState.ENDED, CallState.ERROR],
            CallState.ENDED: [],  # Terminal state
            CallState.TIMEOUT: [],  # Terminal state
            CallState.ERROR: []  # Terminal state
        }
        
        # Call timeout settings
        self.call_timeout = timedelta(minutes=5)
        self.activity_timeout = timedelta(minutes=2)
        
    def create_call(self, channel_id: str, caller_id: Optional[str] = None, 
                   caller_name: Optional[str] = None) -> str:
        """
        Create a new call and return call ID
        
        Args:
            channel_id: Asterisk channel ID
            caller_id: Caller ID number
            caller_name: Caller name
            
        Returns:
            Unique call ID
        """
        call_id = str(uuid.uuid4())
        
        call_data = CallData(
            call_id=call_id,
            channel_id=channel_id,
            state=CallState.RINGING,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            caller_id=caller_id,
            caller_name=caller_name,
            last_activity=datetime.utcnow()
        )
        
        self.calls[call_id] = call_data
        logger.info(f"Created call {call_id} for channel {channel_id}")
        
        # Trigger state entry handler
        asyncio.create_task(self._trigger_state_handlers(call_data))
        
        return call_id
    
    def transition_call(self, call_id: str, new_state: CallState, 
                       error_message: Optional[str] = None) -> bool:
        """
        Transition a call to a new state
        
        Args:
            call_id: Call ID
            new_state: Target state
            error_message: Error message if transitioning to ERROR state
            
        Returns:
            True if transition successful, False otherwise
        """
        if call_id not in self.calls:
            logger.error(f"Call {call_id} not found")
            return False
        
        call_data = self.calls[call_id]
        old_state = call_data.state
        
        # Check if transition is valid
        if new_state not in self.valid_transitions.get(old_state, []):
            logger.error(f"Invalid transition from {old_state} to {new_state} for call {call_id}")
            return False
        
        # Update call data
        call_data.state = new_state
        call_data.updated_at = datetime.utcnow()
        
        if new_state == CallState.ERROR and error_message:
            call_data.error_message = error_message
        
        if new_state in [CallState.LISTENING, CallState.SPEAKING, CallState.PROCESSING]:
            call_data.last_activity = datetime.utcnow()
        
        logger.info(f"Call {call_id} transitioned from {old_state} to {new_state}")
        
        # Trigger transition handlers
        asyncio.create_task(self._trigger_transition_handlers(call_data, old_state, new_state))
        
        # Trigger state entry handlers
        asyncio.create_task(self._trigger_state_handlers(call_data))
        
        return True
    
    def get_call(self, call_id: str) -> Optional[CallData]:
        """Get call data by ID"""
        return self.calls.get(call_id)
    
    def get_call_by_channel(self, channel_id: str) -> Optional[CallData]:
        """Get call data by channel ID"""
        for call_data in self.calls.values():
            if call_data.channel_id == channel_id:
                return call_data
        return None
    
    def end_call(self, call_id: str, reason: str = "normal") -> bool:
        """
        End a call
        
        Args:
            call_id: Call ID
            reason: Reason for ending call
            
        Returns:
            True if successful, False otherwise
        """
        if call_id not in self.calls:
            logger.error(f"Call {call_id} not found")
            return False
        
        call_data = self.calls[call_id]
        
        # Transition to ended state
        success = self.transition_call(call_id, CallState.ENDED)
        
        if success:
            logger.info(f"Ended call {call_id}: {reason}")
        
        return success
    
    def cleanup_call(self, call_id: str) -> bool:
        """
        Remove call from memory (call after cleanup is complete)
        
        Args:
            call_id: Call ID
            
        Returns:
            True if successful, False otherwise
        """
        if call_id in self.calls:
            del self.calls[call_id]
            logger.info(f"Cleaned up call {call_id}")
            return True
        return False
    
    def add_state_handler(self, state: CallState, handler: Callable):
        """Add handler for state entry"""
        if state not in self.state_handlers:
            self.state_handlers[state] = []
        self.state_handlers[state].append(handler)
        logger.debug(f"Added state handler for {state}")
    
    def add_transition_handler(self, from_state: CallState, to_state: CallState, handler: Callable):
        """Add handler for state transition"""
        transition = (from_state, to_state)
        if transition not in self.transition_handlers:
            self.transition_handlers[transition] = []
        self.transition_handlers[transition].append(handler)
        logger.debug(f"Added transition handler for {from_state} -> {to_state}")
    
    async def _trigger_state_handlers(self, call_data: CallData):
        """Trigger handlers for state entry"""
        if call_data.state in self.state_handlers:
            for handler in self.state_handlers[call_data.state]:
                try:
                    await handler(call_data)
                except Exception as e:
                    logger.error(f"Error in state handler for {call_data.state}: {e}")
    
    async def _trigger_transition_handlers(self, call_data: CallData, 
                                         old_state: CallState, new_state: CallState):
        """Trigger handlers for state transition"""
        transition = (old_state, new_state)
        if transition in self.transition_handlers:
            for handler in self.transition_handlers[transition]:
                try:
                    await handler(call_data, old_state, new_state)
                except Exception as e:
                    logger.error(f"Error in transition handler for {old_state} -> {new_state}: {e}")
    
    def get_active_calls(self) -> List[CallData]:
        """Get list of active calls (not ended, timeout, or error)"""
        active_states = {
            CallState.RINGING, CallState.ANSWERED, CallState.LISTENING,
            CallState.SPEAKING, CallState.PROCESSING, CallState.BARGING_IN,
            CallState.TRANSFERRING
        }
        return [call for call in self.calls.values() if call.state in active_states]
    
    def get_calls_by_state(self, state: CallState) -> List[CallData]:
        """Get calls in specific state"""
        return [call for call in self.calls.values() if call.state == state]
    
    def check_timeouts(self) -> List[str]:
        """
        Check for timed out calls
        
        Returns:
            List of call IDs that have timed out
        """
        now = datetime.utcnow()
        timed_out_calls = []
        
        for call_id, call_data in self.calls.items():
            # Check call timeout
            if now - call_data.created_at > self.call_timeout:
                if call_data.state not in [CallState.ENDED, CallState.TIMEOUT, CallState.ERROR]:
                    self.transition_call(call_id, CallState.TIMEOUT)
                    timed_out_calls.append(call_id)
                    logger.warning(f"Call {call_id} timed out after {self.call_timeout}")
            
            # Check activity timeout
            elif (call_data.last_activity and 
                  now - call_data.last_activity > self.activity_timeout and
                  call_data.state in [CallState.LISTENING, CallState.SPEAKING]):
                self.transition_call(call_id, CallState.TIMEOUT)
                timed_out_calls.append(call_id)
                logger.warning(f"Call {call_id} timed out due to inactivity")
        
        return timed_out_calls
    
    def get_stats(self) -> Dict[str, Any]:
        """Get call statistics"""
        stats = {
            "total_calls": len(self.calls),
            "active_calls": len(self.get_active_calls()),
            "calls_by_state": {}
        }
        
        for state in CallState:
            stats["calls_by_state"][state.value] = len(self.get_calls_by_state(state))
        
        return stats


if __name__ == "__main__":
    # Test call state machine
    async def test_state_machine():
        sm = CallStateMachine()
        
        # Create test call
        call_id = sm.create_call("channel-123", "+1234567890", "Test Caller")
        print(f"Created call: {call_id}")
        
        # Test transitions
        print(f"Initial state: {sm.get_call(call_id).state}")
        
        sm.transition_call(call_id, CallState.ANSWERED)
        print(f"After answer: {sm.get_call(call_id).state}")
        
        sm.transition_call(call_id, CallState.LISTENING)
        print(f"After listening: {sm.get_call(call_id).state}")
        
        sm.transition_call(call_id, CallState.SPEAKING)
        print(f"After speaking: {sm.get_call(call_id).state}")
        
        sm.transition_call(call_id, CallState.ENDED)
        print(f"After ended: {sm.get_call(call_id).state}")
        
        # Test stats
        stats = sm.get_stats()
        print(f"Stats: {stats}")
    
    # Run test
    asyncio.run(test_state_machine())
