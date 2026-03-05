import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.infrastructure.setup import tool_registry

async def main():
    print("==========================================")
    print("🔌 正在发起 [真实物理连接] 测试...")
    print("==========================================\n")
    
    try:
        await tool_registry.initialize()
        
        tools = await tool_registry.get_all_tools()
        
        print("\n==========================================")
        print(f"🎉 真实连接成功！当前注册中心共接管了 {len(tools)} 个工具：")
        for tool in tools:
            provider = tool_registry.tool_routing_table.get(tool.name, "未知")
            print(f"  - 🧰 {tool.name} (由 {provider} 提供)")
        print("==========================================\n")
        
    except Exception as e:
        print(f"\n❌ 真实连接失败: {e}")
        
    finally:
        await tool_registry.cleanup()

if __name__ == "__main__":
    asyncio.run(main())