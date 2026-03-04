import asyncio
import sys
import os

# 确保能找到 app 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.infrastructure.mcp.setup import tool_registry

async def main():
    print("==========================================")
    print("🔌 正在发起 [真实物理连接] 测试...")
    print("==========================================\n")
    
    try:
        # 1. 真实唤醒所有 JSON 里配置的服务器
        await tool_registry.initialize()
        
        # 2. 真实索要工具列表
        tools = await tool_registry.get_all_tools()
        
        print("\n==========================================")
        print(f"🎉 真实连接成功！当前注册中心共接管了 {len(tools)} 个工具：")
        for tool in tools:
            # 打印工具名和归属的节点
            provider = tool_registry.tool_routing_table.get(tool.name, "未知")
            print(f"  - 🧰 {tool.name} (由 {provider} 提供)")
        print("==========================================\n")
        
    except Exception as e:
        print(f"\n❌ 真实连接失败: {e}")
        
    finally:
        # 3. 真实关闭所有子进程
        await tool_registry.cleanup()

if __name__ == "__main__":
    # 直接运行，不走 unittest 框架
    asyncio.run(main())