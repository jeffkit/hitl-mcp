#!/usr/bin/env python3
"""
Forward Service 配置迁移脚本

将旧的 forward_rules.json 配置迁移到新的 forward_bots.json 格式（多 Bot 支持）

运行方式:
    python migrate_forward_config.py
"""
import os
import json
import sys
from pathlib import Path

def load_json(path: str) -> dict:
    """加载 JSON 文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"❌ 加载 {path} 失败: {e}")
        return {}

def save_json(path: str, data: dict):
    """保存 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ 已保存到 {path}")
    except Exception as e:
        print(f"❌ 保存 {path} 失败: {e}")

def migrate():
    """执行迁移"""
    print("🔄 Forward Service 配置迁移")
    print("从旧格式迁移到新格式（多 Bot 支持）")
    print("")
    
    # 路径
    project_root = Path(__file__).parent
    old_config_path = project_root / "forward_config.json"
    old_rules_path = project_root / "data" / "forward_rules.json"
    new_config_path = project_root / "data" / "forward_bots.json"
    
    # 检查新配置是否已存在
    if new_config_path.exists():
        print(f"⚠️  新配置文件已存在: {new_config_path}")
        response = input("是否覆盖？(y/N): ")
        if response.lower() != 'y':
            print("❌ 取消迁移")
            sys.exit(0)
    
    # 从环境变量或旧配置读取
    bot_key = os.getenv("FORWARD_BOT_KEY", "")
    forward_url = os.getenv("FORWARD_URL", "")
    
    # 尝试从旧配置文件读取
    if old_config_path.exists():
        print(f"📄 找到旧配置文件: {old_config_path}")
        old_config = load_json(str(old_config_path))
        bot_key = bot_key or old_config.get("bot_key", "")
        forward_url = forward_url or old_config.get("default_url", "")
    
    # 尝试从旧规则文件读取
    old_rules = {}
    if old_rules_path.exists():
        print(f"📄 找到旧规则文件: {old_rules_path}")
        old_rules = load_json(str(old_rules_path))
    
    # 检查是否有数据可迁移
    if not bot_key and not forward_url and not old_rules:
        print("⚠️  未找到可迁移的配置")
        print("提示：")
        print("  - 设置环境变量 FORWARD_BOT_KEY 和 FORWARD_URL")
        print("  - 或创建 forward_config.json 文件")
        sys.exit(1)
    
    # 设置默认 bot_key
    if not bot_key:
        bot_key = "default_migrated_key"
        print(f"⚠️  未设置 FORWARD_BOT_KEY，使用默认值: {bot_key}")
    
    print(f"\n📊 迁移信息:")
    print(f"  Bot Key: {bot_key}")
    print(f"  默认 URL: {forward_url or '(未设置)'}")
    print(f"  旧规则数: {len(old_rules)}")
    print("")
    
    # 创建新配置
    new_config = {
        "default_bot_key": bot_key,
        "bots": {
            bot_key: {
                "bot_key": bot_key,
                "name": "默认机器人（从旧配置迁移）",
                "description": "自动从旧配置迁移 - " + str(Path.cwd()),
                "forward_config": {
                    "url_template": forward_url,
                    "agent_id": "",
                    "api_key": "",
                    "timeout": 60
                },
                "access_control": {
                    "mode": "allow_all",
                    "whitelist": [],
                    "blacklist": []
                },
                "enabled": True
            }
        }
    }
    
    # 如果有旧规则，创建提示
    if old_rules:
        print("⚠️  注意：旧的 chat_id 规则已不适用于新版本")
        print("   新版本基于 bot_key（从 webhook_url 提取）进行路由")
        print("   旧规则内容已忽略")
        print("")
    
    # 保存新配置
    save_json(str(new_config_path), new_config)
    
    print("")
    print("✅ 迁移完成！")
    print("")
    print("📝 后续步骤:")
    print("  1. 检查新配置文件: data/forward_bots.json")
    print("  2. 根据需要调整配置（Bot 名称、URL、访问控制等）")
    print("  3. 重启 Forward Service")
    print("")
    print("💡 提示:")
    print("  - 多 Bot 支持：可以在 bots 中添加更多 Bot 配置")
    print("  - 访问控制：设置 access_control.mode 为 whitelist 或 blacklist")
    print("  - 管理台：访问 /admin 查看和编辑配置")

if __name__ == "__main__":
    migrate()
