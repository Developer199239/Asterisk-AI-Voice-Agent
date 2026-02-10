"""
Live Agent Transfer Tool - explicit handoff to configured live agent destination.

This tool is a thin, config-driven wrapper around blind_transfer so operators can:
- enable/disable a dedicated "live agent" action per context in Admin UI, and
- control which transfer destination key represents the live agent.
"""

from typing import Any, Dict, Optional, Tuple, List, Mapping

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
            cfg = destinations.get(configured_key)
            # Prevent misrouting "live agent" to arbitrary destinations: only accept
            # keys explicitly marked live_agent (or the conventional key name).
            if isinstance(cfg, dict) and (bool(cfg.get("live_agent")) or configured_key == "live_agent"):
                return configured_key, "config.live_agent_destination_key"
            return None, "configured_key_missing"

        live_agent_keys: List[str] = []
        for key, cfg in destinations.items():
            if isinstance(cfg, dict) and bool(cfg.get("live_agent")):
                live_agent_keys.append(str(key))
        if len(live_agent_keys) == 1:
            return live_agent_keys[0], "destinations.<key>.live_agent"
        if len(live_agent_keys) > 1:
            return None, "destinations.live_agent_ambiguous"

        if "live_agent" in destinations:
            return "live_agent", "default.live_agent_key"

        return None, "unconfigured"

    @classmethod
    def _resolve_live_agent_extension_from_internal_config(
        cls,
        extensions_cfg: Dict[str, Any],
    ) -> Tuple[Optional[str], Dict[str, Any], str]:
        if not isinstance(extensions_cfg, dict) or not extensions_cfg:
            return None, {}, "extensions.internal.empty"

        def _numeric_extension_key(key: Any) -> Optional[str]:
            ext = str(key or "").strip()
            if ext and ext.isdigit():
                return ext
            return None

        def _contains_live_agent(cfg: Mapping[str, Any]) -> bool:
            hay = f"{cls._normalize_text(cfg.get('name'))} {cls._normalize_text(cfg.get('description'))}".strip()
            tokens = [t for t in cls._normalize_text("live agent").split() if t]
            return bool(tokens) and all(t in hay for t in tokens)

        explicit_flag: List[Tuple[str, Dict[str, Any]]] = []
        text_match: List[Tuple[str, Dict[str, Any]]] = []
        alias_match: List[Tuple[str, Dict[str, Any]]] = []

        for key, cfg in extensions_cfg.items():
            extension = _numeric_extension_key(key)
            if not extension or not isinstance(cfg, dict):
                continue
            # Treat missing 'transfer' as enabled (UI defaults to true).
            if cfg.get("transfer") is False:
                continue

            if bool(cfg.get("live_agent")):
                explicit_flag.append((extension, dict(cfg)))

            if _contains_live_agent(cfg):
                text_match.append((extension, dict(cfg)))

            aliases = cfg.get("aliases")
            alias_values = aliases if isinstance(aliases, list) else [aliases] if aliases is not None else []
            if any(cls._normalize_text(alias) == "live agent" for alias in alias_values):
                alias_match.append((extension, dict(cfg)))

        if len(explicit_flag) == 1:
            ext, entry = explicit_flag[0]
            return ext, entry, "extensions.internal.live_agent_flag"
        if len(explicit_flag) > 1:
            return None, {}, "extensions.internal.live_agent_flag_ambiguous"

        if len(text_match) == 1:
            ext, entry = text_match[0]
            return ext, entry, "extensions.internal.text_live_agent"
        if len(text_match) > 1:
            return None, {}, "extensions.internal.text_live_agent_ambiguous"

        if len(alias_match) == 1:
            ext, entry = alias_match[0]
            return ext, entry, "extensions.internal.alias_live_agent"
        if len(alias_match) > 1:
            return None, {}, "extensions.internal.alias_live_agent_ambiguous"

        return None, {}, "extensions.internal.unconfigured"

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
            # Only map to destinations explicitly marked as live-agent (or the conventional key),
            # otherwise we risk labeling a live-agent transfer as "Support agent", etc.
            if key != "live_agent" and not bool(cfg.get("live_agent")):
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
            extension, ext_entry, ext_source = self._resolve_live_agent_extension_from_internal_config(extensions_cfg)
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

            display_name = str(ext_entry.get("name", "") or "").strip()
            display_desc = str(ext_entry.get("description", "") or "").strip()
            description = display_name or display_desc or "Live agent"

            logger.info(
                "Resolved live agent transfer via direct internal extension fallback",
                call_id=context.call_id,
                extension=extension,
                resolution_source=ext_source,
            )
            return await UnifiedTransferTool()._transfer_to_extension(context, extension, description)

        logger.info(
            "Executing live agent transfer",
            call_id=context.call_id,
            destination_key=destination_key,
            resolution_source=source,
        )

        # Reuse canonical blind transfer execution path to avoid logic duplication.
        return await UnifiedTransferTool().execute({"destination": destination_key}, context)
