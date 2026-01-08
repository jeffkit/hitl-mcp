#!/usr/bin/env python3
"""
快速测试: 发送 MD 文档到企业微信

使用方式:
1. 修改下面的 CHAT_ID 为你的群/私聊 ID
2. 确保 HIL Server 正在运行 (http://localhost:8081)
3. 运行脚本: python quick_send.py
"""

import requests
from pathlib import Path

# ==================== 配置区域 ====================
HIL_SERVER_URL = "http://localhost:8081"
CHAT_ID = "your_chat_id"  # ⚠️ 请修改为实际的 chat_id
# ==================================================

# 读取 MD 文件
md_file = Path(__file__).parent / "test_document.md"
md_content = md_file.read_text(encoding="utf-8")

print("="*60)
print("准备发送 MD 文档到企业微信")
print("="*60)
print(f"📄 文件: {md_file}")
print(f"📝 大小: {len(md_content)} 字符")
print(f"💬 Chat ID: {CHAT_ID}")
print()

if CHAT_ID == "your_chat_id":
    print("⚠️  请先修改脚本中的 CHAT_ID 为实际的群/私聊 ID")
    exit(1)

# 发送消息
print("📤 正在发送...")

try:
    response = requests.post(
        f"{HIL_SERVER_URL}/api/send-message",
        json={
            "message": md_content,
            "chat_id": CHAT_ID,
            "chat_type": "group",
            "timeout": 1200,
            "wait_reply": True
        },
        timeout=10
    )

    result = response.json()

    if result.get("success"):
        session_id = result.get("session_id")
        print(f"✅ 发送成功!")
        print(f"🆔 会话 ID: {session_id}")
        print(f"\n💡 提示:")
        print(f"   - 消息已发送到企业微信")
        print(f"   - 企业微信会渲染 Markdown 格式")
        print(f"   - 你可以回复此消息进行交互")
        print(f"   - 会话超时时间: 20 分钟")
    else:
        print(f"❌ 发送失败: {result.get('error')}")

except requests.exceptions.ConnectionError:
    print(f"❌ 无法连接到 HIL Server ({HIL_SERVER_URL})")
    print(f"💡 请确保 HIL Server 正在运行")
except Exception as e:
    print(f"❌ 错误: {e}")

print("="*60)
