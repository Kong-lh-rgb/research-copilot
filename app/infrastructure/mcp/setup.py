# 拿到可用的工具
import logging
import json
import os
from typing import Any, Dict, List, Optional
from mcp.types import Tool

from app.infrastructure.mcp.client import MCPToolClient

logger = logging.getLogger(__name__)

class MCPRegistry:
    def __init__(self):
        self.clients:Dict[str, MCPToolClient] = {}
        self.tool_routing_table: Dict[str, str] = {}
    async def initialize(self) -> None:
        """读取配置文件，批量启动并注册所有 MCP 服务"""
        logger.info("🚀 开始读取配置文件并初始化 MCP 注册中心...")
        
        # 定位项目根目录下的 mcp_servers.json
        # 当前路径: app/infrastructure/mcp/setup.py，往上退三层到项目根目录
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        config_path = os.path.join(base_dir, 'mcp_servers.json')
        
        if not os.path.exists(config_path):
            logger.warning(f"⚠️ 未找到配置文件: {config_path}，将跳过外部工具加载。")
            return

        # 1. 解析 JSON 配置
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 格式错误: {e}")
            return

        # 2. 动态实例化客户端
        for server_name, server_config in config.get("mcpServers", {}).items():
            command = server_config.get("command")
            args = server_config.get("args", [])
            env = server_config.get("env")
            
            # 使用基础构造函数直接传入底层命令
            self.clients[server_name] = MCPToolClient(command=command, args=args, env=env)
            logger.info(f"⏳ 正在注册服务: [{server_name}]...")

        # 3. 批量启动并构建全局路由表
        for service_name, client in self.clients.items():
            try:
                # 唤醒外部进程并握手
                await client.start()
                # 索要该服务提供的所有工具
                tools = await client.get_tools()
                
                # 将工具打上服务标签，存入路由表
                for tool in tools:
                    self.tool_routing_table[tool.name] = service_name
                    
                logger.info(f"✅ 服务 [{service_name}] 启动成功，已挂载 {len(tools)} 个工具。")
            except Exception as e:
                logger.error(f"❌ 服务 [{service_name}] 启动失败，请检查配置或环境: {e}")

    async def get_all_tools(self) -> List[Tool]:
        """获取全局所有可用的工具列表 (未来喂给大模型用)"""
        all_tools = []
        for client in self.clients.values():
            if client._session: # 确保已连接
                tools = await client.get_tools()
                all_tools.extend(tools)
        return all_tools

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        统一的工具执行网关：Agent 只需报工具名，网关自动寻址执行
        """
        if tool_name not in self.tool_routing_table:
            raise ValueError(f"未知工具: '{tool_name}'，注册中心未找到对应的提供方！")
            
        service_name = self.tool_routing_table[tool_name]
        client = self.clients[service_name]
        
        logger.info(f"🚦 网关路由: 拦截到 [{tool_name}] 请求，分发至节点 -> [{service_name}]")
        return await client.call_tool(tool_name, arguments)

    async def cleanup(self) -> None:
        """全局安全断电，释放所有子进程和管道"""
        logger.info("🛑 准备断开所有 MCP 服务...")
        for name, client in self.clients.items():
            await client.close()
            logger.info(f"[-] 已断开: {name}")
        self.clients.clear()
        self.tool_routing_table.clear()
        logger.info("✅ 资源清理完毕。")

# 导出全局单例，整个 FastAPI 应用生命周期内共享这一个注册中心
tool_registry = MCPRegistry()