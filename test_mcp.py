import asyncio
import logging
logging.basicConfig(level=logging.INFO)
from app.infrastructure.setup import tool_registry

async def main():
    await tool_registry.initialize()
    print("Initial get_all_tools:")
    tools = await tool_registry.get_all_tools()
    print(len(tools))
    
    await asyncio.sleep(2)
    
    print("Second get_all_tools:")
    try:
        tools2 = await tool_registry.get_all_tools()
        print(len(tools2))
    except Exception as e:
        import traceback
        traceback.print_exc()
    
    await tool_registry.cleanup()

asyncio.run(main())
