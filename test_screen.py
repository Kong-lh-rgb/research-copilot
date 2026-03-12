import json
import asyncio
from app.infrastructure.local_server import mcp

async def test():
    # 测试筛选: 价格小于5，市值大于100亿
    from app.infrastructure.local_server import screen_stocks
    res = screen_stocks(
        max_price=5.0,
        limit=5
    )
    print("Test Result:")
    # print raw text
    print(res)
    
    # Try parsing
    try:
        data = json.loads(res)
        print("Count:", data.get("count"))
        if data.get("count", 0) > 0:
            print("First stock:", data["stocks"][0])
    except Exception as e:
        print("Parse error:", e)

if __name__ == "__main__":
    asyncio.run(test())
