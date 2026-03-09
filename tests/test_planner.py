import pytest

from app.graph.nodes import planner as planner_module


@pytest.mark.asyncio
async def test_planner_node_success(monkeypatch):
    async def fake_call_llm(**kwargs):
        return {
            "content": """[
                {"task_id": "t1", "description": "收集财报", "dependencies": []},
                {"task_id": "t2", "description": "对比分析", "dependencies": ["t1"]}
            ]"""
        }

    monkeypatch.setattr(planner_module, "call_llm", fake_call_llm)
    result = await planner_module.planner_node({"user_input": "请帮我拆解调研任务"})

    assert set(result["tasks"].keys()) == {"t1", "t2"}
    assert result["ready_tasks"] == ["t1"]
    assert result["running_tasks"] == []


@pytest.mark.asyncio
async def test_planner_node_empty_input_fallback():
    result = await planner_module.planner_node({"user_input": ""})
    assert result == {"tasks": {}}
