"""
Live Agent Transfer Tool - explicit handoff to configured live agent destination.

This tool is a thin, config-driven wrapper around blind_transfer so operators can:
- enable/disable a dedicated "live agent" action per context in Admin UI, and
- control which transfer destination key represents the live agent.
"""

from typing import Any, Dict, Optional, Tuple

import structlog

from src.tools.base import Tool, ToolCategory, ToolDefinition
from src.tools.context import ToolExecutionContext
from src.tools.telephony.unified_transfer import UnifiedTransferTool

logger = structlog.get_logger(__name__)


class LiveAgentTransferTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="live_agent_transfer",
            description=(
                "Transfer the caller to the configured live agent destination. "
                "Destination is configured in Tools -> Transfer -> Live Agent Destination Key."
            ),
            category=ToolCategory.TELEPHONY,
            requires_channel=True,
            max_execution_time=30,
            parameters=[],
        )

    @staticmethod
    def _resolve_live_agent_destination_key(
        transfer_cfg: Dict[str, Any],
    ) -> Tuple[Optional[str], str]:
        destinations = (transfer_cfg.get("destinations") or {}) if isinstance(transfer_cfg, dict) else {}
        if not isinstance(destinations, dict) or not destinations:
            return None, "no_destinations"

        configured_key = str(transfer_cfg.get("live_agent_destination_key") or "").strip()
        if configured_key:
            if configured_key in destinations:
                return configured_key, "config.live_agent_destination_key"
            return None, "configured_key_missing"

        for key, cfg in destinations.items():
            if isinstance(cfg, dict) and bool(cfg.get("live_agent")):
                return str(key), "destinations.<key>.live_agent"

        if "live_agent" in destinations:
            return "live_agent", "default.live_agent_key"

        return None, "unconfigured"

    async def execute(self, parameters: Dict[str, Any], context: ToolExecutionContext) -> Dict[str, Any]:
        _ = parameters
        transfer_cfg = context.get_config_value("tools.transfer") or {}
        if isinstance(transfer_cfg, dict) and transfer_cfg.get("enabled") is False:
            return {"status": "failed", "message": "Transfer service is disabled"}

        destination_key, source = self._resolve_live_agent_destination_key(transfer_cfg)
        if not destination_key:
            logger.warning(
                "Live agent transfer destination not configured",
                call_id=context.call_id,
                resolution_source=source,
            )
            return {
                "status": "failed",
                "message": (
                    "Live agent destination is not configured. "
                    "Set tools.transfer.live_agent_destination_key in Tools settings."
                ),
            }

        logger.info(
            "Executing live agent transfer",
            call_id=context.call_id,
            destination_key=destination_key,
            resolution_source=source,
        )

        # Reuse canonical blind transfer execution path to avoid logic duplication.
        return await UnifiedTransferTool().execute({"destination": destination_key}, context)
