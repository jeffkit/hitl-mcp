"""
项目配置命令处理

处理用户的项目管理斜杠命令：
- /add-project - 添加项目配置
- /list-projects - 列出用户的项目
- /use - 切换项目
- /set-default - 设置默认项目
- /remove-project - 删除项目
- /current-project - 查看当前项目
"""
import logging
import re
from typing import Tuple

from ..database import get_db_manager
from ..repository import get_user_project_repository

logger = logging.getLogger(__name__)


# ============== 命令正则匹配 ==============
# 每个命令都有简写版本：/add-project = /ap, /list-projects = /lp 等

ADD_PROJECT_RE = re.compile(
    r'^/(?:add-project|ap)\s+(\S+)\s+(\S+)'  # project_id, url
    r'(?:\s+--api-key\s+(\S+))?'       # optional: api_key
    r'(?:\s+--name\s+(.+?))?'          # optional: project_name
    r'(?:\s+--timeout\s+(\d+))?'       # optional: timeout
    r'(?:\s+--default)?$',             # optional: is_default flag
    re.IGNORECASE
)

LIST_PROJECTS_RE = re.compile(
    r'^/(?:list-projects|projects|lp)\s*$',
    re.IGNORECASE
)

USE_PROJECT_RE = re.compile(
    r'^/(?:use|u)\s+(\S+)$',
    re.IGNORECASE
)

SET_DEFAULT_RE = re.compile(
    r'^/(?:set-default|sd)\s+(\S+)$',
    re.IGNORECASE
)

REMOVE_PROJECT_RE = re.compile(
    r'^/(?:remove-project|rp)\s+(\S+)$',
    re.IGNORECASE
)

CURRENT_PROJECT_RE = re.compile(
    r'^/(?:current-project|current|cp)\s*$',
    re.IGNORECASE
)


# ============== 命令处理函数 ==============

async def handle_add_project(
    bot_key: str,
    chat_id: str,
    message: str
) -> Tuple[bool, str]:
    """
    处理 /add-project 命令

    用法: /add-project <project_id> <url> [--api-key <key>] [--name <name>] [--timeout <sec>] [--default]

    示例:
    /add-project test https://api.test.com/webhook --api-key sk123 --default
    /add-project prod https://api.prod.com/webhook --name "生产环境"
    """
    match = ADD_PROJECT_RE.match(message.strip())
    if not match:
        return False, "❌ 命令格式错误\n\n用法: /add-project <project_id> <url> [--api-key <key>] [--name <name>] [--timeout <sec>] [--default]"

    project_id = match.group(1)
    url = match.group(2)
    api_key = match.group(3) if match.lastindex >= 3 else None
    project_name = match.group(4) if match.lastindex >= 4 else None
    timeout = int(match.group(5)) if match.lastindex >= 5 and match.group(5) else 300
    is_default = match.group(0).endswith("--default") or False

    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 1. 先检查项目 ID 是否已存在（按 bot_key + chat_id + project_id 联合去重）
            existing = await repo.get_by_project_id(bot_key, chat_id, project_id)
            if existing:
                return False, f"❌ 项目 `{project_id}` 已存在\n\n💡 使用 `/projects` 或 `/lp` 查看已有项目\n💡 使用 `/rp {project_id}` 可删除后重新添加"

            # 2. 测试连通性
            test_result = await _test_agent_connectivity(url, api_key)
            
            # 连接失败时拒绝保存
            if not test_result["success"]:
                lines = [
                    "❌ **连接测试失败，项目未保存**",
                    "",
                    f"🔗 URL: `{url}`",
                ]
                
                if api_key:
                    masked_key = api_key[:4] + "***" + api_key[-4:] if len(api_key) > 8 else "***"
                    lines.append(f"🔐 API Key: `{masked_key}`")
                
                lines.append("")
                lines.append(f"❌ 错误: {test_result['error']}")
                if test_result.get('response'):
                    lines.append(f"📋 响应: {test_result['response'][:300]}")
                lines.append("")
                lines.append("💡 请检查 URL 和 API Key 是否正确后重试")
                lines.append("📖 文档: https://agentstudio.woa.com/docs/qywx-bot")
                
                return False, "\n".join(lines)

            # 3. 连接成功，创建项目配置
            _project = await repo.create(
                bot_key=bot_key,
                chat_id=chat_id,
                project_id=project_id,
                url_template=url,
                api_key=api_key,
                project_name=project_name,
                timeout=timeout,
                is_default=is_default,
                enabled=True
            )

            # 格式化成功响应
            lines = [
                "🎉 **项目添加成功！**",
                "",
                f"📦 项目ID: `{project_id}`",
                f"🔗 URL: `{url}`",
            ]

            if api_key:
                masked_key = api_key[:4] + "***" + api_key[-4:] if len(api_key) > 8 else "***"
                lines.append(f"🔐 API Key: `{masked_key}`")

            if project_name:
                lines.append(f"📛 项目名称: {project_name}")

            if is_default:
                lines.append("⭐ 已设为默认项目")

            lines.append("")
            lines.append("✅ **连接测试成功！**")
            lines.append("")
            lines.append("💡 **下一步**：直接发送消息开始对话！")

            return True, "\n".join(lines)

    except Exception as e:
        logger.error(f"添加项目失败: {e}", exc_info=True)
        return False, f"❌ 添加项目失败: {str(e)}"


async def _test_agent_connectivity(url: str, api_key: str | None) -> dict:
    """
    测试 Agent 连通性
    
    发送一个测试消息，检查是否能正常响应
    
    Returns:
        {"success": bool, "error": str?, "response": str?}
    """
    import httpx
    
    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # 发送测试消息
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                json={"message": "ping"},
                headers=headers
            )
            
            if response.status_code == 200:
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "response": response.text
                }
    except httpx.TimeoutException:
        return {"success": False, "error": "连接超时 (15秒)"}
    except httpx.ConnectError as e:
        return {"success": False, "error": f"无法连接: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_list_projects(
    bot_key: str,
    chat_id: str
) -> Tuple[bool, str]:
    """
    处理 /list-projects 或 /projects 命令

    列出用户在当前 Bot 下的所有项目配置
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            projects = await repo.get_user_projects(bot_key, chat_id, enabled_only=False)

            if not projects:
                return True, "📭 暂无项目配置\n\n💡 使用 `/add-project <id> <url>` 添加第一个项目"

            lines = ["📋 **我的项目配置**\n"]

            for p in projects:
                # 默认标记
                default_mark = "⭐" if p.is_default else "📦"
                enabled_mark = "" if p.enabled else "❌️"

                # 项目名称显示
                name_display = p.project_name if p.project_name else p.project_id

                lines.append(f"{default_mark} `{p.project_id}`{enabled_mark} - {name_display}")
                lines.append(f"   🔗 {p.url_template}")

                if p.api_key:
                    lines.append("   🔑 API Key: ***")

                if p.timeout != 300:
                    lines.append(f"   ⏱️ 超时: {p.timeout}秒")

                lines.append("")  # 空行分隔

            lines.append("---")
            lines.append("💡 用法:")
            lines.append("  `/use <project_id>` - 切换项目")
            lines.append("  `/add-project <id> <url>` - 添加新项目")
            lines.append("  `/set-default <id>` - 设为默认")
            lines.append("  `/remove-project <id>` - 删除项目")

            return True, "\n".join(lines)

    except Exception as e:
        logger.error(f"列出项目失败: {e}", exc_info=True)
        return False, f"❌ 获取项目列表失败: {str(e)}"


async def handle_set_default(
    bot_key: str,
    chat_id: str,
    project_id: str
) -> Tuple[bool, str]:
    """
    处理 /set-default 命令

    用法: /set-default <project_id>
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 检查项目是否存在
            project = await repo.get_by_project_id(bot_key, chat_id, project_id)
            if not project:
                return False, f"❌ 项目 `{project_id}` 不存在\n\n💡 使用 `/list-projects` 查看已有项目"

            if not project.enabled:
                return False, f"❌ 项目 `{project_id}` 已禁用"

            # 设置为默认
            success = await repo.set_default(bot_key, chat_id, project_id)

            if success:
                return True, f"✅ 已将项目 `{project_id}` 设为默认"
            else:
                return False, "❌ 设置默认项目失败"

    except Exception as e:
        logger.error(f"设置默认项目失败: {e}", exc_info=True)
        return False, f"❌ 设置失败: {str(e)}"


async def handle_remove_project(
    bot_key: str,
    chat_id: str,
    project_id: str
) -> Tuple[bool, str]:
    """
    处理 /remove-project 命令

    用法: /remove-project <project_id>
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 检查项目是否存在
            project = await repo.get_by_project_id(bot_key, chat_id, project_id)
            if not project:
                return False, f"❌ 项目 `{project_id}` 不存在"

            # 删除项目
            success = await repo.delete_by_project_id(bot_key, chat_id, project_id)

            if success:
                return True, f"✅ 项目 `{project_id}` 已删除"
            else:
                return False, "❌ 删除项目失败"

    except Exception as e:
        logger.error(f"删除项目失败: {e}", exc_info=True)
        return False, f"❌ 删除失败: {str(e)}"


async def handle_use_project(
    bot_key: str,
    chat_id: str,
    project_id: str,
    user_id: str = ""
) -> Tuple[bool, str]:
    """
    处理 /use 命令

    用法: /use <project_id>

    功能：切换到指定项目（更新当前会话的项目）
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 检查项目是否存在
            project = await repo.get_by_project_id(bot_key, chat_id, project_id)
            if not project:
                return False, f"❌ 项目 `{project_id}` 不存在\n\n💡 使用 `/list-projects` 查看已有项目"

            if not project.enabled:
                return False, f"❌ 项目 `{project_id}` 已禁用"

        # 更新会话的项目 ID
        if user_id:
            from ..session_manager import get_session_manager
            session_mgr = get_session_manager()
            await session_mgr.set_session_project(user_id, chat_id, bot_key, project_id)

        # 构建成功消息
        lines = [
            f"✅ 已切换到项目 `{project_id}`",
            f"📦 项目名称: {project.project_name or project_id}",
            f"🔗 转发目标: `{project.url_template}`",
        ]

        if project.api_key:
            lines.append("🔑 API Key: ***")

        if project.timeout != 300:
            lines.append(f"⏱️ 超时: {project.timeout}秒")

        lines.append("")
        lines.append("💡 现在可以开始对话了！")

        return True, "\n".join(lines)

    except Exception as e:
        logger.error(f"切换项目失败: {e}", exc_info=True)
        return False, f"❌ 切换失败: {str(e)}"


async def handle_current_project(
    bot_key: str,
    chat_id: str
) -> Tuple[bool, str]:
    """
    处理 /current-project 或 /current 命令

    显示用户当前使用的项目（默认项目）
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 获取默认项目
            project = await repo.get_default_project(bot_key, chat_id)

            if not project:
                return True, "📭 暂无默认项目\n\n💡 使用 `/add-project <id> <url> --default` 添加并设为默认"

            lines = [
                "📋 **当前项目**",
                f"📦 项目ID: `{project.project_id}`",
            ]

            if project.project_name:
                lines.append(f"📛 项目名称: {project.project_name}")

            lines.append(f"🔗 URL: `{project.url_template}`")

            if project.api_key:
                lines.append("🔑 API Key: ***")

            if project.timeout != 300:
                lines.append(f"⏱️ 超时: {project.timeout}秒")

            return True, "\n".join(lines)

    except Exception as e:
        logger.error(f"获取当前项目失败: {e}", exc_info=True)
        return False, f"❌ 获取失败: {str(e)}"


def is_project_command(message: str) -> bool:
    """
    判断消息是否是项目配置命令

    Returns:
        True 如果是项目命令
    """
    message = message.strip()

    return bool(
        ADD_PROJECT_RE.match(message) or
        LIST_PROJECTS_RE.match(message) or
        USE_PROJECT_RE.match(message) or
        SET_DEFAULT_RE.match(message) or
        REMOVE_PROJECT_RE.match(message) or
        CURRENT_PROJECT_RE.match(message)
    )


async def handle_project_command(
    bot_key: str,
    chat_id: str,
    message: str,
    user_id: str = ""
) -> Tuple[bool, str]:
    """
    处理项目配置命令

    Args:
        bot_key: Bot Key
        chat_id: 用户/群 ID
        message: 消息内容
        user_id: 用户 ID（用于 /use 命令更新会话）

    Returns:
        (success, response_message)
    """
    message = message.strip()

    # /add-project
    if ADD_PROJECT_RE.match(message):
        return await handle_add_project(bot_key, chat_id, message)

    # /list-projects or /projects
    elif LIST_PROJECTS_RE.match(message):
        return await handle_list_projects(bot_key, chat_id)

    # /set-default
    elif SET_DEFAULT_RE.match(message):
        match = SET_DEFAULT_RE.match(message)
        project_id = match.group(1)
        return await handle_set_default(bot_key, chat_id, project_id)

    # /remove-project
    elif REMOVE_PROJECT_RE.match(message):
        match = REMOVE_PROJECT_RE.match(message)
        project_id = match.group(1)
        return await handle_remove_project(bot_key, chat_id, project_id)

    # /current-project or /current
    elif CURRENT_PROJECT_RE.match(message):
        return await handle_current_project(bot_key, chat_id)

    # /use
    elif USE_PROJECT_RE.match(message):
        match = USE_PROJECT_RE.match(message)
        project_id = match.group(1)
        return await handle_use_project(bot_key, chat_id, project_id, user_id)

    return False, "❌ 未知的项目命令"


def get_user_help() -> str:
    """
    获取新用户帮助信息（没有绑定任何项目）
    
    当 Bot 没有配置转发目标且用户没有绑定项目时显示
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    return f"""👋 **欢迎使用！**

请先绑定一个 Agent 项目：

📦 **添加项目**
```
/ap <项目ID> <URL> --api-key <API_KEY> [--default]
```

示例:
```
/ap test https://agentstudio.woa.com/a2a/xxx/messages --api-key sk-xxx --default
```

📖 **获取 URL 和 API-Key**
👉 https://agentstudio.woa.com/docs/qywx-bot

💡 常用命令：
• `/lp` - 查看我的项目
• `/cp` - 当前项目
• `/help` - 帮助

---
⏱️ {timestamp}"""


def get_regular_user_help() -> str:
    """
    获取普通用户帮助信息（已绑定项目）
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    return f"""📖 **用户帮助**

📦 **项目管理**
• `/lp` (`/projects`) - 查看我的项目
• `/ap <ID> <URL> --api-key <KEY>` - 添加项目
• `/u <ID>` (`/use`) - 切换项目
• `/sd <ID>` (`/set-default`) - 设为默认
• `/rp <ID>` (`/remove-project`) - 删除项目
• `/cp` (`/current`) - 当前项目

💬 **会话管理**
• `/s` - 列出会话
• `/r` - 重置会话
• `/c <ID>` - 切换会话

📖 文档：https://agentstudio.woa.com/docs/qywx-bot

---
⏱️ {timestamp}"""


def get_admin_full_help() -> str:
    """
    获取管理员帮助信息（包含所有命令）
    """
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    return f"""📖 **管理员帮助**

🔧 **系统状态**
• `/ping` - 健康检查
• `/status` - 系统状态

🤖 **Bot 管理**
• `/bots` - 列出所有 Bot
• `/bot <name>` - 查看详情
• `/bot <name> url <URL>` - 修改 URL
• `/bot <name> key <KEY>` - 修改 API Key

📊 **请求监控**
• `/pending` - 处理中的请求
• `/recent` - 最近日志
• `/errors` - 错误日志

🏥 **运维**
• `/health` - Agent 可达性检查

---

📦 **项目管理**
• `/lp` (`/projects`) - 查看我的项目
• `/ap <ID> <URL> --api-key <KEY>` - 添加项目
• `/u <ID>` (`/use`) - 切换项目
• `/sd <ID>` (`/set-default`) - 设为默认
• `/rp <ID>` (`/remove-project`) - 删除项目
• `/cp` (`/current`) - 当前项目

💬 **会话管理**
• `/s` - 列出会话
• `/r` - 重置会话
• `/c <ID>` - 切换会话

---
⏱️ {timestamp}"""
