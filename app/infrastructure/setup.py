import logging
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from mcp.types import Tool

from dotenv import load_dotenv
load_dotenv()

from app.infrastructure.client import MCPToolClient

logger = logging.getLogger(__name__)

# 项目根目录（用于将相对路径 script 转换为绝对路径）
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _expand_env(value: Any) -> Any:
    """递归展开字符串中的 ${ENV_VAR} 占位符dict/list 递归处理。"""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _resolve_binary(name: str) -> str:
    """
    动态寻找可执行文件路径：
    1. 优先读取 {NAME_UPPER}_BIN 环境变量
    2. 降级到 shutil.which(name)
    3. 再降级直接返回 name
    """
    env_key = f"{name.upper()}_BIN"
    from_env = os.getenv(env_key, "").strip()
    if from_env:
        return from_env
    found = shutil.which(name)
    if found:
        return found
    logger.warning(f"⚠️ 未在 PATH 中找到 [{name}]，将直接使用名称，请确保其在 PATH 中可用。")
    return name


class MCPRegistry:
    def __init__(self):
        self.clients: Dict[str, MCPToolClient] = {}
        self.tool_routing_table: Dict[str, str] = {}

    def _build_client_from_config(self, server_name: str, server_config: Dict[str, Any]) -> MCPToolClient:
        # 先展开所有 ${} 占位符
        cfg = _expand_env(server_config)

        # 始终以父进程完整环境变量为基础，再叠加配置文件中的 env 覆盖项
        # 这样子进程能继承 SENDER_EMAIL / SENDER_PASSWORD 等主进程的变量
        env = os.environ.copy()
        env_from_cfg: Optional[Dict[str, str]] = cfg.get("env")
        if env_from_cfg:
            env.update(env_from_cfg)
        
        cwd: Optional[str] = cfg.get("cwd")

        # ── 直接指定 command 模式 ──
        if "command" in cfg:
            command = cfg.get("command")
            args = cfg.get("args", [])
            if not command:
                raise ValueError(f"服务 [{server_name}] 缺少有效 command")
            if not isinstance(args, list):
                raise ValueError(f"服务 [{server_name}] 的 args 必须是数组")
            return MCPToolClient(command=command, args=args, env=env, cwd=cwd)

        server_type = cfg.get("type")
        args = cfg.get("args", [])
        if not isinstance(args, list):
            raise ValueError(f"服务 [{server_name}] 的 args 必须是数组")

        # ── Node.js (npx) 模式 ──
        if server_type == "node":
            package = cfg.get("package")
            if not package:
                raise ValueError(f"Node 服务 [{server_name}] 缺少 package")
            npx_bin = _resolve_binary("npx")
            return MCPToolClient.from_npx(package=package, args=args, env=env, npx_bin=npx_bin)

        # ── Python (uv) 模式 ──
        if server_type == "python":
            script_or_package = (
                cfg.get("script_or_package")
                or cfg.get("script")
                or cfg.get("package")
            )
            if not script_or_package:
                raise ValueError(f"Python 服务 [{server_name}] 缺少 script_or_package/script/package")

            uv_bin = _resolve_binary("uv")

            if cwd:
                if cwd.startswith("$") or not cwd:
                    raise ValueError(
                        f"Python 服务 [{server_name}] 的 cwd 环境变量未展开（当前值: '{cwd}'）。"
                        f"请在 .env 中设置对应的环境变量。"
                    )
                # 如果 script 看似是本地文件（例如以 .py 结尾），基于 cwd 解析为绝对路径
                if script_or_package.endswith(".py"):
                    script_path = Path(cwd) / script_or_package
                    script_or_package = str(script_path.resolve())

                return MCPToolClient.from_python(
                    script_or_package=script_or_package,
                    args=args,
                    env=env,
                    cwd=cwd,
                    uv_bin=uv_bin,
                )
            else:
                # 无 cwd：若是本地文件，基于项目根目录解析为绝对路径
                script_path = Path(script_or_package)
                if script_or_package.endswith(".py") and not script_path.is_absolute():
                    script_path = _PROJECT_ROOT / script_path
                    script_or_package = str(script_path.resolve())

                return MCPToolClient.from_python(
                    script_or_package=script_or_package,
                    args=args,
                    env=env,
                    uv_bin=uv_bin,
                )

        raise ValueError(
            f"服务 [{server_name}] 配置格式不支持：请使用 command/args 或 type=node|python"
        )

    async def initialize(self) -> None:
        """读取配置文件，批量启动并注册所有 MCP 服务"""
        logger.info("🚀 开始读取配置文件并初始化 MCP 注册中心...")

        base_dir = _PROJECT_ROOT
        config_path = base_dir / "mcp_servers.json"

        if not config_path.exists():
            logger.warning(f"⚠️ 未找到配置文件: {config_path}，将跳过外部工具加载。")
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
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
        """获取全局所有可用的工具列表。单个客户端失败时跳过并告警，不影响其他工具可用性。"""
        all_tools = []
        for service_name, client in self.clients.items():
            if not client._session:
                continue
            try:
                tools = await client.get_tools()
                all_tools.extend(tools)
            except Exception as e:
                logger.error(f"❌ 获取 [{service_name}] 工具列表失败，跳过: {e}")
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