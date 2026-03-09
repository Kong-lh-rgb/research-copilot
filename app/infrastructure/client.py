import logging
import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.types import Tool

logger = logging.getLogger(__name__)


class MCPToolClient:
    """
    标准的 MCP 客户端封装类。
    支持长驻进程（startup 时启动，cleanup 时关闭），
    避免每次工具调用重新 fork 进程的性能问题。
    """

    def __init__(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ):
        """基础构造函数：直接接收底层的 command、args、env 和 cwd"""
        self.command = command
        self.args = args
        self.env = env
        self.cwd = cwd

        self._session: Optional[ClientSession] = None
        self._exit_stack = AsyncExitStack()

    @classmethod
    def from_npx(
        cls,
        package: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        npx_bin: str = "npx",
    ) -> "MCPToolClient":
        """
        启动 Node.js (npx) 编写的 MCP Server。
        npx_bin 由外部动态寻址传入，默认 "npx"。
        """
        full_args = ["-y", package]
        if args:
            full_args.extend(args)
        return cls(command=npx_bin, args=full_args, env=env)

    @classmethod
    def from_python(
        cls,
        script_or_package: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        uv_bin: str = "uv",
    ) -> "MCPToolClient":
        """
        启动 Python (uv run) 编写的 MCP Server。
        uv_bin 由外部动态寻址传入，默认 "uv"。
        script_or_package 应为绝对路径或 pypi 包名。
        """
        full_args = ["run", script_or_package]
        if args:
            full_args.extend(args)
        return cls(command=uv_bin, args=full_args, env=env, cwd=cwd)

    async def start(self) -> None:
        """启动 MCP 服务并完成握手初始化。"""
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )
        stdio_transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self._read, self._write = stdio_transport

        self._session = await self._exit_stack.enter_async_context(
            ClientSession(self._read, self._write)
        )
        await self._session.initialize()

        logger.info(f"✅ MCP 客户端已连接: {self.command} {' '.join(self.args)}")

    async def restart(self) -> None:
        """关闭并重新启动 MCP 连接（子进程意外退出时自动恢复）。"""
        logger.warning(f"🔄 MCP 子进程已断开，尝试重连: {self.command} {' '.join(self.args)}")
        try:
            await self._exit_stack.aclose()
        except Exception:
            pass
        self._session = None
        self._exit_stack = AsyncExitStack()
        await self.start()
        logger.info(f"✅ MCP 重连成功: {self.command} {' '.join(self.args)}")

    async def get_tools(self) -> List[Tool]:
        """获取该 MCP Server 暴露的工具列表，连接断开时自动重连一次。"""
        if not self._session:
            raise RuntimeError("MCP 客户端未启动，请先调用 start()")
        try:
            response = await self._session.list_tools()
            return response.tools
        except Exception as e:
            logger.warning(f"⚠️ list_tools 失败（{e}），尝试重连...")
            await self.restart()
            response = await self._session.list_tools()
            return response.tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """执行指定工具，连接断开时自动重连一次。"""
        if not self._session:
            raise RuntimeError("MCP 客户端未启动，请先调用 start()")
        logger.info(f"🔧 执行工具: {name} | 参数: {arguments}")
        try:
            return await self._session.call_tool(name, arguments)
        except Exception as e:
            logger.warning(f"⚠️ call_tool [{name}] 失败（{e}），尝试重连...")
            await self.restart()
            return await self._session.call_tool(name, arguments)

    async def close(self) -> None:
        """优雅关闭：断开连接并清理资源。"""
        try:
            await self._exit_stack.aclose()
        except RuntimeError:
            pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"关闭连接时出现未知警告: {e}")

        logger.info("🛑 MCP 连接已安全关闭")