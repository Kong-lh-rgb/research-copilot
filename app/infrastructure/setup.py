import logging
import json
import os
from typing import Any, Dict, List, Optional
from mcp.types import Tool

from app.infrastructure.client import MCPToolClient

logger = logging.getLogger(__name__)

class MCPRegistry:
    def __init__(self):
        self.clients:Dict[str, MCPToolClient] = {}
        self.tool_routing_table: Dict[str, str] = {}

    def _build_client_from_config(self, server_name: str, server_config: Dict[str, Any]) -> MCPToolClient:
        env = server_config.get("env")

        if "command" in server_config:
            command = server_config.get("command")
            args = server_config.get("args", [])
            if not command:
                raise ValueError(f"服务 [{server_name}] 缺少有效 command")
            if not isinstance(args, list):
                raise ValueError(f"服务 [{server_name}] 的 args 必须是数组")
            return MCPToolClient(command=command, args=args, env=env)

        server_type = server_config.get("type")
        args = server_config.get("args", [])
        if not isinstance(args, list):
            raise ValueError(f"服务 [{server_name}] 的 args 必须是数组")

        if server_type == "node":
            package = server_config.get("package")
            if not package:
                raise ValueError(f"Node 服务 [{server_name}] 缺少 package")
            return MCPToolClient.from_npx(package=package, args=args, env=env)

        if server_type == "python":
            script_or_package = server_config.get("script_or_package") or server_config.get("script") or server_config.get("package")
            if not script_or_package:
                raise ValueError(f"Python 服务 [{server_name}] 缺少 script_or_package/script/package")
            return MCPToolClient.from_python(script_or_package=script_or_package, args=args, env=env)

        raise ValueError(
            f"服务 [{server_name}] 配置格式不支持：请使用 command/args 或 type=node|python"
        )

    async def initialize(self) -> None:
        """读取配置文件，批量启动并注册所有 MCP 服务"""
        logger.info("🚀 开始读取配置文件并初始化 MCP 注册中心...")
        
 
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        config_path = os.path.join(base_dir, 'mcp_servers.json')
        
        if not os.path.exists(config_path):
            logger.warning(f"⚠️ 未找到配置文件: {config_path}，将跳过外部工具加载。")
            return


        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式错误: {e}")
            return


        for server_name, server_config in config.get("mcpServers", {}).items():
            try:
                self.clients[server_name] = self._build_client_from_config(server_name, server_config)
                logger.info(f"⏳ 正在注册服务: [{server_name}]...")
            except ValueError as e:
                logger.error(f"❌ 跳过非法配置: {e}")

        for service_name, client in self.clients.items():
            try:
                await client.start()
                tools = await client.get_tools()
                
                for tool in tools:
                    self.tool_routing_table[tool.name] = service_name
                    
                logger.info(f"✅ 服务 [{service_name}] 启动成功，已挂载 {len(tools)} 个工具。")
            except Exception as e:
                logger.error(f"❌ 服务 [{service_name}] 启动失败，请检查配置或环境: {e}")

    async def get_all_tools(self) -> List[Tool]:
        """获取全局所有可用的工具列表。"""
        all_tools = []
        for client in self.clients.values():
            if client._session:
                tools = await client.get_tools()
                all_tools.extend(tools)
        return all_tools

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """统一的工具执行网关。"""
        if tool_name not in self.tool_routing_table:
            raise ValueError(f"未知工具: '{tool_name}'，注册中心未找到对应的提供方！")
            
        service_name = self.tool_routing_table[tool_name]
        client = self.clients[service_name]
        
        logger.info(f"🚦 网关路由: 拦截到 [{tool_name}] 请求，分发至节点 -> [{service_name}]")
        return await client.call_tool(tool_name, arguments)

    async def cleanup(self) -> None:
        """释放所有子进程和管道。"""
        logger.info("🛑 准备断开所有 MCP 服务...")
        for name, client in self.clients.items():
            await client.close()
            logger.info(f"[-] 已断开: {name}")
        self.clients.clear()
        self.tool_routing_table.clear()
        logger.info("✅ 资源清理完毕。")

tool_registry = MCPRegistry()