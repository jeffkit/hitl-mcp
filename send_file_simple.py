#!/usr/bin/env python3
"""
测试发送文件附件到 devg

直接在请求中包含文件数据,不需要先上传
"""
import requests
import sys
import base64
from pathlib import Path

# ==================== 配置区域 ====================
HIL_SERVER_URL = "http://9.134.172.68:8081"
CHAT_ID = "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A"
FILE_PATH = Path(__file__).parent / "test_document.md"
# ==================================================

print("="*60)
print("📤 测试发送文件附件到 devg HIL Server")
print("="*60)
print(f"🌐 HIL Server: {HIL_SERVER_URL}")
print(f"💬 Chat ID: {CHAT_ID}")
print(f"📄 文件路径: {FILE_PATH}")
print()

if not FILE_PATH.exists():
    print(f"❌ 文件不存在: {FILE_PATH}")
    sys.exit(1)

# 读取文件并编码为 base64
with open(FILE_PATH, "rb") as f:
    file_content = f.read()
    file_b64 = base64.b64encode(file_content).decode("utf-8")

print(f"📦 文件大小: {len(file_content)} bytes")
print(f"📦 Base64 大小: {len(file_b64)} chars")
print()

# 发送文件消息
print("📤 发送文件消息...")
print("-"*60)

try:
    response = requests.post(
        f"{HIL_SERVER_URL}/api/send",
        json={
            "message": f"📎 请查收文件: {FILE_PATH.name}",
            "chat_id": CHAT_ID,
            "chat_type": "group",
            "timeout": 3600,
            "wait_reply": True,
            "file_data": {
                "content": file_b64,
                "filename": FILE_PATH.name
            }
        },
        timeout=30
    )

    print(f"HTTP 状态码: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        print(f"响应: {result}")

        if result.get("success"):
            session_id = result.get("session_id")
            print("\n" + "="*60)
            print("✅ 文件发送成功!")
            print("="*60)
            print(f"🆔 会话 ID: {session_id}")
            print(f"📄 文件名: {FILE_PATH.name}")
            print(f"📏 文件大小: {len(file_content)} bytes")
            print(f"💬 你应该能在企业微信中看到文件附件了!")
            print(f"\n💡 提示:")
            print(f"   - 文件以附件形式发送")
            print(f"   - 用户可以直接下载/查看")
            print(f"   - 可以回复此消息进行交互")
        else:
            print(f"\n❌ 发送失败: {result.get('error')}")
    else:
        print(f"❌ HTTP 错误: {response.status_code}")
        print(f"响应: {response.text}")

except Exception as e:
    print(f"❌ 发送失败: {e}")
    import traceback
    traceback.print_exc()

print("="*60)
