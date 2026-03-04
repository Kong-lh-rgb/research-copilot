from unittest.mock import patch

from app.graph.nodes.planner import planner_node


def test_planner_node_success():
    with patch("app.graph.nodes.planner.call_llm", return_value={"content": "[]", "tool_calls": None, "raw": {}}):
        result = planner_node({"user_input": "请帮我拆解调研任务"})
    assert result == {"task_list": "[]"}


def test_planner_node_empty_input_fallback():
    result = planner_node({"user_input": ""})
    assert result == {"task_list": []}


if __name__ == "__main__":
    test_planner_node_success()
    test_planner_node_empty_input_fallback()
    print("planner tests passed")
