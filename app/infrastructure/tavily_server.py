import os
import json
import logging
import sys
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# 配置日志，输出到 stderr 以便调试
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Define the server
mcp = FastMCP("Tavily Search API")

logger.info("开始初始化 Tavily Search MCP Server...")

@mcp.tool()
def tavily_search(query: str, count: int = 5, search_depth: str = "basic") -> str:
    """
    Search the web using Tavily Search API. 
    Ideal for real-time information, news, code problems, or general queries.
    
    Args:
        query: The search query string.
        count: Number of search results to return (default: 5).
        search_depth: "basic" or "advanced". "advanced" provides more thorough research (default: "basic").
    """
    logger.debug(f"tavily_search 被调用: query={query}, count={count}, search_depth={search_depth}")
    
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        error_msg = "Error: TAVILY_API_KEY environment variable is not set."
        logger.error(error_msg)
        return error_msg
        
    try:
        # 导入 tavily 库
        from tavily import TavilyClient
        
        logger.debug(f"创建 TavilyClient 实例...")
        client = TavilyClient(api_key=api_key)
        
        logger.debug(f"开始执行搜索...")
        response = client.search(
            query=query, 
            max_results=count,
            search_depth=search_depth,
            include_answer=False
        )
        
        logger.debug(f"收到搜索响应: {len(response.get('results', []))} 个结果")
        
        # Format the results into a readable string
        results = response.get("results", [])
        if not results:
            return "No results found."
            
        formatted_results = []
        for i, res in enumerate(results, 1):
            title = res.get("title", "No Title")
            url = res.get("url", "")
            content = res.get("content", "")
            
            result_str = f"[{i}] {title}\nURL: {url}\nSummary: {content}\n"
            formatted_results.append(result_str)
        
        result = "\n".join(formatted_results)
        logger.debug(f"搜索成功，返回结果长度: {len(result)}")
        return result
        
    except ImportError as e:
        error_msg = f"Error: tavily library not installed: {str(e)}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Error executing Tavily search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg

if __name__ == "__main__":
    logger.info("MCP Server 启动...")
    mcp.run()

