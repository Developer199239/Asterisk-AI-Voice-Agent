"""
Unit tests for LiveAgentTransferTool.
"""

import pytest

from src.tools.telephony.live_agent_transfer import LiveAgentTransferTool


class TestLiveAgentTransferTool:
    @pytest.fixture
    def tool(self):
        return LiveAgentTransferTool()

    def test_definition(self, tool):
        d = tool.definition
        assert d.name == "live_agent_transfer"
        assert d.category.value == "telephony"
        assert d.requires_channel is True
        assert len(d.parameters) == 0

    @pytest.mark.asyncio
    async def test_uses_explicit_live_agent_destination_key(self, tool, tool_context, mock_ari_client):
        tool_context.config["tools"]["transfer"] = {
            "enabled": True,
            "live_agent_destination_key": "tier2_live",
            "destinations": {
                "sales_agent": {"type": "extension", "target": "2765", "description": "Sales"},
                "tier2_live": {"type": "extension", "target": "6000", "description": "Live Agent", "live_agent": True},
            },
        }

        result = await tool.execute({}, tool_context)

        assert result["status"] == "success"
        assert result["destination"] == "6000"
        call_args = mock_ari_client.send_command.call_args.kwargs
        assert call_args["resource"] == f"channels/{tool_context.caller_channel_id}/continue"
        assert call_args["params"]["extension"] == "6000"

    @pytest.mark.asyncio
    async def test_falls_back_to_live_agent_key_when_config_not_set(self, tool, tool_context, mock_ari_client):
        tool_context.config["tools"]["transfer"] = {
            "enabled": True,
            "destinations": {
                "live_agent": {"type": "extension", "target": "6001", "description": "Live Agent"},
            },
        }

        result = await tool.execute({}, tool_context)

        assert result["status"] == "success"
        assert result["destination"] == "6001"
        call_args = mock_ari_client.send_command.call_args.kwargs
        assert call_args["resource"] == f"channels/{tool_context.caller_channel_id}/continue"
        assert call_args["params"]["extension"] == "6001"

    @pytest.mark.asyncio
    async def test_fails_when_live_agent_destination_not_configured(self, tool, tool_context):
        tool_context.config["tools"]["transfer"] = {
            "enabled": True,
            "destinations": {
                "sales_agent": {"type": "extension", "target": "2765", "description": "Sales"},
            },
        }
        tool_context.config["tools"]["extensions"] = {
            "internal": {
                "2765": {"name": "Sales Agent", "aliases": ["sales"], "dial_string": "SIP/2765"},
            }
        }

        result = await tool.execute({}, tool_context)
        assert result["status"] == "failed"
        assert "Live agent destination is not configured" in result["message"]

    @pytest.mark.asyncio
    async def test_falls_back_to_internal_live_agent_extension_and_maps_to_transfer_destination(
        self, tool, tool_context, mock_ari_client
    ):
        tool_context.config["tools"]["transfer"] = {
            "enabled": True,
            "destinations": {
                "support_agent": {"type": "extension", "target": "6000", "description": "Support agent"},
                "live_agent": {"type": "extension", "target": "6000", "description": "Live Agent"},
            },
        }
        tool_context.config["tools"]["extensions"] = {
            "internal": {
                "6000": {
                    "name": "Live Agent",
                    "aliases": ["agent", "human"],
                    "dial_string": "SIP/6000",
                    "description": "Live customer service representative",
                },
            }
        }

        result = await tool.execute({}, tool_context)

        assert result["status"] == "success"
        assert result["destination"] == "6000"
        call_args = mock_ari_client.send_command.call_args.kwargs
        assert call_args["resource"] == f"channels/{tool_context.caller_channel_id}/continue"
        assert call_args["params"]["extension"] == "6000"

    @pytest.mark.asyncio
    async def test_falls_back_to_internal_live_agent_extension_without_transfer_destinations(
        self, tool, tool_context, mock_ari_client
    ):
        tool_context.config["tools"]["transfer"] = {
            "enabled": True,
            "destinations": {},
        }
        tool_context.config["tools"]["extensions"] = {
            "internal": {
                "7007": {
                    "name": "Live Agent",
                    "aliases": ["live agent"],
                    "dial_string": "PJSIP/7007",
                    "description": "Escalation desk",
                },
            }
        }

        result = await tool.execute({}, tool_context)

        assert result["status"] == "success"
        assert result["destination"] == "7007"
        call_args = mock_ari_client.send_command.call_args.kwargs
        assert call_args["resource"] == f"channels/{tool_context.caller_channel_id}/continue"
        assert call_args["params"]["extension"] == "7007"

    @pytest.mark.asyncio
    async def test_ignores_misconfigured_live_agent_destination_key_and_uses_internal_extension(
        self, tool, tool_context, mock_ari_client
    ):
        tool_context.config["tools"]["transfer"] = {
            "enabled": True,
            # Misconfigured: points at a normal destination (not marked live_agent).
            "live_agent_destination_key": "support_agent",
            "destinations": {
                "support_agent": {"type": "extension", "target": "2765", "description": "Support agent"},
            },
        }
        tool_context.config["tools"]["extensions"] = {
            "internal": {
                "6000": {"name": "Live Agent", "description": "Live customer service rep", "dial_string": "SIP/6000", "transfer": True},
            }
        }

        result = await tool.execute({}, tool_context)

        assert result["status"] == "success"
        assert result["destination"] == "6000"
        call_args = mock_ari_client.send_command.call_args.kwargs
        assert call_args["resource"] == f"channels/{tool_context.caller_channel_id}/continue"
        assert call_args["params"]["extension"] == "6000"
