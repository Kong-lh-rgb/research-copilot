import pytest

from app.graph.nodes import controller as controller_module


@pytest.mark.asyncio
async def test_controller_node_simple_chat(monkeypatch):
    async def fake_call_llm(**kwargs):
        return {"content": '{"intent": "simple_chat"}'}

    monkeypatch.setattr(controller_module, "call_llm", fake_call_llm)
    result = await controller_module.controller_node({"user_input": "你好"})
    assert result["next_action"] == "simple_chat"


@pytest.mark.asyncio
async def test_controller_node_fallback_to_complex(monkeypatch):
    async def fake_call_llm(**kwargs):
        return {"content": "not json"}

    monkeypatch.setattr(controller_module, "call_llm", fake_call_llm)
    result = await controller_module.controller_node({"user_input": "随便问一下"})
    assert result["next_action"] == "complex_research"