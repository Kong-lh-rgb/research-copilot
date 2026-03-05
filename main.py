import asyncio
import logging
import sys
sys.path.insert(0, "/Users/linghang/agent/deep-researcher")

logging.getLogger("httpx").setLevel(logging.WARNING)

from app.graph.build_graph import build_graph
from app.infrastructure.setup import tool_registry
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


async def main():
    await tool_registry.initialize()

    async with AsyncSqliteSaver.from_conn_string("memory.db") as checkpointer:
        app = build_graph().compile(checkpointer=checkpointer)

        while True:
            query = input("请输入查询内容: ")

            # 每轮只传入新消息和当前任务输入，历史 message 由 checkpointer + add_messages 自动累积
            turn_state = {
                "messages": [{"role": "user", "content": query}],
                "user_input": query,
                "tasks": {},
                "next_action": "",
            }

            final_reply = ""
            async for step in app.astream(
                turn_state,
                config={"configurable": {"thread_id": "user_123"}}
            ):
                for node_output in step.values():
                    if isinstance(node_output, dict) and "final_report" in node_output:
                        final_reply = node_output["final_report"]

            if final_reply:
                print(f"\nAI: {final_reply}\n")

    await tool_registry.cleanup()


if __name__ == "__main__":
    asyncio.run(main())