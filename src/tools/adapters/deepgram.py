"""
Deepgram Voice Agent adapter for tool calling.

Handles translation between unified tool format and Deepgram's function calling format.
"""

from typing import Dict, Any, List
from src.tools.registry import ToolRegistry
from src.tools.context import ToolExecutionContext
import json
import logging

logger = logging.getLogger(__name__)


class DeepgramToolAdapter:
    """
    Adapter for Deepgram Voice Agent API tool calling.
    
    Translates between unified tool format and Deepgram's specific event format.
    """
    
    def __init__(self, registry: ToolRegistry):
        """
        Initialize adapter with tool registry.
        
        Args:
            registry: ToolRegistry instance with registered tools
        """
        self.registry = registry
    
    def get_tools_config(self) -> List[Dict[str, Any]]:
        """
        Get tools configuration in Deepgram format.
        
        Returns:
            List of tool schemas for Deepgram session initialization
        
        Example:
            [
                {
                    "name": "transfer_call",
                    "description": "Transfer caller to extension",
                    "parameters": {
                        "type": "object",
                        "properties": {...},
                        "required": [...]
                    }
                }
            ]
        """
        schemas = self.registry.to_deepgram_schema()
        logger.debug(f"Generated Deepgram schemas for {len(schemas)} tools")
        return schemas
    
    async def handle_tool_call_event(
        self,
        event: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle function call event from Deepgram.
        
        Deepgram event format:
        {
            "type": "FunctionCallRequest",
            "function_name": "transfer_call",
            "parameters": {
                "target": "2765"
            }
        }
        
        Args:
            event: Function call event from Deepgram
            context: Execution context dict with:
                - call_id
                - caller_channel_id
                - bridge_id
                - session_store
                - ari_client
                - config
        
        Returns:
            Tool execution result dict
        """
        function_name = event.get('function_name')
        parameters = event.get('parameters', {})
        
        logger.info(f"🔧 Deepgram tool call: {function_name}({parameters})")
        
        # Get tool from registry
        tool = self.registry.get(function_name)
        if not tool:
            error_msg = f"Unknown tool: {function_name}"
            logger.error(error_msg)
            return {
                "status": "error",
                "message": error_msg
            }
        
        # Build execution context
        exec_context = ToolExecutionContext(
            call_id=context['call_id'],
            caller_channel_id=context.get('caller_channel_id'),
            bridge_id=context.get('bridge_id'),
            session_store=context['session_store'],
            ari_client=context['ari_client'],
            config=context.get('config'),
            provider_name="deepgram",
            user_input=context.get('user_input')
        )
        
        # Execute tool
        try:
            result = await tool.execute(parameters, exec_context)
            logger.info(f"✅ Tool {function_name} executed: {result.get('status')}")
            return result
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                "status": "error",
                "message": error_msg,
                "error": str(e)
            }
    
    async def send_tool_result(
        self,
        result: Dict[str, Any],
        context: Dict[str, Any]
    ) -> None:
        """
        Send tool execution result back to Deepgram.
        
        Result format sent to Deepgram:
        {
            "type": "FunctionCallResponse",
            "status": "success" | "failed" | "error",
            "output": "Human-readable message",
            "data": {...}
        }
        
        Args:
            result: Tool execution result
            context: Context dict with websocket connection
        """
        websocket = context.get('websocket')
        if not websocket:
            logger.error("No websocket in context, cannot send tool result")
            return
        
        response = {
            "type": "FunctionCallResponse",
            "status": result.get('status', 'unknown'),
            "output": result.get('message', ''),
            "data": result
        }
        
        try:
            await websocket.send(json.dumps(response))
            logger.debug(f"Sent tool result to Deepgram: {response['status']}")
        except Exception as e:
            logger.error(f"Failed to send tool result to Deepgram: {e}", exc_info=True)
