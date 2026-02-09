"""
Live Agent Transfer Tool - explicit handoff to configured live agent destination.

This tool is a thin, config-driven wrapper around blind_transfer so operators can:
- enable/disable a dedicated "live agent" action per context in Admin UI, and
- control which transfer destination key represents the live agent.
"""

from typing import Any, Dict, Optional, Tuple, List

import structlog

from src.tools.base import Tool, ToolCategory, ToolDefinition
from src.tools.context import ToolExecutionContext
from src.tools.telephony.unified_transfer import UnifiedTransferTool

logger = structlog.get_logger(__name__)


class LiveAgentTransferTool(Tool):
    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())

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

    @classmethod
    def _resolve_live_agent_extension_from_internal_config(
        cls,
        extensions_cfg: Dict[str, Any],
    ) -> Tuple[Optional[str], str]:
        if not isinstance(extensions_cfg, dict) or not extensions_cfg:
            return None, "extensions.internal.empty"

        def _numeric_extension_key(key: Any) -> Optional[str]:
            ext = str(key or "").strip()
            if ext and ext.isdigit():
                return ext
            return None

        explicit_flag: List[str] = []
        name_match: List[str] = []
        alias_match: List[str] = []

        for key, cfg in extensions_cfg.items():
            extension = _numeric_extension_key(key)
            if not extension or not isinstance(cfg, dict):
                continue

            if bool(cfg.get("live_agent")):
                explicit_flag.append(extension)

            if cls._normalize_text(cfg.get("name")) == "live agent":
                name_match.append(extension)

            aliases = cfg.get("aliases")
            alias_values = aliases if isinstance(aliases, list) else [aliases] if aliases is not None else []
            if any(cls._normalize_text(alias) == "live agent" for alias in alias_values):
                alias_match.append(extension)

        if len(explicit_flag) == 1:
            return explicit_flag[0], "extensions.internal.live_agent_flag"
        if len(explicit_flag) > 1:
            return None, "extensions.internal.live_agent_flag_ambiguous"

        if len(name_match) == 1:
            return name_match[0], "extensions.internal.name_live_agent"
        if len(name_match) > 1:
            return None, "extensions.internal.name_live_agent_ambiguous"

        if len(alias_match) == 1:
            return alias_match[0], "extensions.internal.alias_live_agent"
        if len(alias_match) > 1:
            return None, "extensions.internal.alias_live_agent_ambiguous"

        return None, "extensions.internal.unconfigured"

    @staticmethod
    def _map_extension_to_transfer_destination_key(
        extension: str,
        transfer_cfg: Dict[str, Any],
    ) -> Optional[str]:
        destinations = (transfer_cfg.get("destinations") or {}) if isinstance(transfer_cfg, dict) else {}
        matches: List[str] = []

        for key, cfg in destinations.items():
            if not isinstance(cfg, dict):
                continue
            transfer_type = str(cfg.get("type", "") or "").strip().lower()
            target = str(cfg.get("target", "") or "").strip()
            if transfer_type == "extension" and target == extension:
                matches.append(str(key))

        if len(matches) == 1:
            return matches[0]

        return None

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

            extensions_cfg = context.get_config_value("tools.extensions.internal") or {}
            extension, ext_source = self._resolve_live_agent_extension_from_internal_config(extensions_cfg)
            if not extension:
                return {
                    "status": "failed",
                    "message": (
                        "Live agent destination is not configured. "
                        "Set tools.transfer.live_agent_destination_key, mark a transfer destination "
                        "as live_agent, or configure tools.extensions.internal with a Live Agent extension."
                    ),
                }

            mapped_destination_key = self._map_extension_to_transfer_destination_key(extension, transfer_cfg)
            if mapped_destination_key:
                logger.info(
                    "Resolved live agent transfer via internal extension mapping",
                    call_id=context.call_id,
                    extension=extension,
                    destination_key=mapped_destination_key,
                    resolution_source=ext_source,
                )
                return await UnifiedTransferTool().execute({"destination": mapped_destination_key}, context)

            logger.info(
                "Resolved live agent transfer via direct internal extension fallback",
                call_id=context.call_id,
                extension=extension,
                resolution_source=ext_source,
            )
            return await UnifiedTransferTool()._transfer_to_extension(context, extension, "Live agent")

        logger.info(
            "Executing live agent transfer",
            call_id=context.call_id,
            destination_key=destination_key,
            resolution_source=source,
        )

        # Reuse canonical blind transfer execution path to avoid logic duplication.
        return await UnifiedTransferTool().execute({"destination": destination_key}, context)
