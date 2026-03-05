import asyncio
import sys
sys.path.insert(0, "/Users/linghang/agent/deep-researcher")

from app.graph.build_graph import build_graph
from app.infrastructure.setup import tool_registry


async def main():
    # 初始化 MCP 工具注册中心，建立与外部 MCP 服务的连接
    await tool_registry.initialize()

    try:
        graph = build_graph()
        app = graph.compile()

        state = {
            "user_input": "对比上海电气和比亚迪的近期股价并且发送邮件到我的邮箱2163579781@qq.com",
            "next_action": "",
            "tasks": {}
        }

        async for step in app.astream(state):
            print("\n==== STEP ====")
            print(step)
    finally:
        # 无论成功还是失败，都清理 MCP 连接
        await tool_registry.cleanup()


if __name__ == "__main__":
    asyncio.run(main())