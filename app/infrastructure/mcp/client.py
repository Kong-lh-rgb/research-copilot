import logging
from typing import Any, Dict, List, Optional
from contextlib import AsyncExitStack

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.types import Tool

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class MCPToolClient:
    """
    标准的 MCP 客户端封装类
    """
    def __init__(self, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        """基础构造函数：直接接收底层的 command 和 args"""
        self.command = command
        self.args = args
        self.env = env
        
        self._session: Optional['ClientSession'] = None
        self._exit_stack = AsyncExitStack()



    @classmethod
    def from_npx(cls, package: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> "MCPToolClient":
        """
        专门用于启动 Node.js (npx) 编写的 MCP Server
        例如: MCPToolClient.from_npx("@modelcontextprotocol/server-brave-search")
        """

        full_args = ["-y", package]
        if args:
            full_args.extend(args)
        return cls(command="npx", args=full_args, env=env)

    @classmethod
    def from_python(cls, script_or_package: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None) -> "MCPToolClient":
        """
        专门用于启动 Python (uv) 编写的 MCP Server
        例如: MCPToolClient.from_python("mcp-server-sqlite", args=["--db", "test.db"])
        """

        full_args = ["run", script_or_package]
        if args:
            full_args.extend(args)
        return cls(command="uv", args=full_args, env=env)



    async def start(self) -> None:
        """1. 启动服务并握手"""
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env
        )
        stdio_transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        self._read, self._write = stdio_transport
        
        self._session = await self._exit_stack.enter_async_context(ClientSession(self._read, self._write))
        await self._session.initialize()
        
        logger.info(f"✅ MCP 客户端已连接: {self.command} {' '.join(self.args)}")

    async def get_tools(self) -> List[Tool]:
        """2. 获取工具列表"""
        if not self._session:
            raise RuntimeError("客户端未启动！")
        response = await self._session.list_tools()
        return response.tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """3. 执行工具"""
        if not self._session:
            raise RuntimeError("客户端未启动！")
        logger.info(f"🔧 执行工具: {name} | 参数: {arguments}")
        return await self._session.call_tool(name, arguments)

    async def close(self) -> None:
        """4. 优雅关闭"""
        await self._exit_stack.aclose()
        logger.info("🛑 MCP 连接已关闭")