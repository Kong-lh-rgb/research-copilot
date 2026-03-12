import os
import json
from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient

# Define the server
mcp = FastMCP("Tavily Search API")

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
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY environment variable is not set."
        
    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query, 
            max_results=count,
            search_depth=search_depth,
            include_answer=False
        )
        
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
            
        return "\n".join(formatted_results)
        
    except Exception as e:
        return f"Error executing Tavily search: {str(e)}"

if __name__ == "__main__":
    mcp.run()
