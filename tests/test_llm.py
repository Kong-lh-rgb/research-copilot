import pytest

from app.llm.client import get_llm


def test_get_llm_client_instance():
    get_llm.cache_clear()
    llm = get_llm()
    assert llm is not None
    assert hasattr(llm, "chat")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_integration_chat(integration_enabled):
    if not integration_enabled:
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run external LLM call")

    get_llm.cache_clear()
    llm = get_llm()
    response = await llm.chat(messages=[{"role": "user", "content": "你好"}], temperature=0)
    assert isinstance(response, dict)