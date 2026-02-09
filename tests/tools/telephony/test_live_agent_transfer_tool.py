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
                "tier2_live": {"type": "extension", "target": "6000", "description": "Live Agent"},
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

        result = await tool.execute({}, tool_context)
        assert result["status"] == "failed"
        assert "Live agent destination is not configured" in result["message"]
