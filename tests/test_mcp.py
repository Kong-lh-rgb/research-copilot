import pytest

from app.infrastructure.setup import tool_registry


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_registry_integration(integration_enabled):
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run external MCP registry test")

    try:
        await tool_registry.initialize()
        tools = await tool_registry.get_all_tools()
        assert isinstance(tools, list)
    finally:
        await tool_registry.cleanup()