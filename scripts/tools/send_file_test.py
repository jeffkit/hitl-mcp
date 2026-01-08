#!/usr/bin/env python3
"""
测试发送文件附件到企业微信

需要先上传文件获取 media_id,然后再发送文件消息
"""
import requests
import sys
from pathlib import Path

# ==================== 配置区域 ====================
HIL_SERVER_URL = "https://hitl.woa.com"
CHAT_ID = "wokSFfCgAAimChUpCX7QnUR8_mlwkU3A"
FILE_PATH = Path(__file__).parent / "test_document.md"
# ==================================================

print("="*60)
print("📤 测试发送文件附件到企业微信")
print("="*60)
print(f"🌐 HIL Server: {HIL_SERVER_URL}")
print(f"💬 Chat ID: {CHAT_ID}")
print(f"📄 文件路径: {FILE_PATH}")
print()

if not FILE_PATH.exists():
    print(f"❌ 文件不存在: {FILE_PATH}")
    sys.exit(1)

# 步骤1: 上传文件
print("步骤1: 上传文件...")
print("-"*60)

try:
    with open(FILE_PATH, "rb") as f:
        files = {"file": (FILE_PATH.name, f, "text/markdown")}
        response = requests.post(
            f"{HIL_SERVER_URL}/api/upload-file",
            files=files,
            timeout=60,
            verify=False
        )

    print(f"HTTP 状态码: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        print(f"响应: {result}")

        if result.get("success"):
            media_id = result.get("media_id")
            print(f"\n✅ 文件上传成功!")
            print(f"🆔 Media ID: {media_id}")
        else:
            print(f"\n❌ 上传失败: {result.get('error')}")
            sys.exit(1)
    else:
        print(f"❌ HTTP 错误: {response.status_code}")
        print(f"响应: {response.text}")
        sys.exit(1)

except Exception as e:
    print(f"❌ 上传文件失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# 步骤2: 发送文件消息
print("步骤2: 发送文件消息...")
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
            "files": {
                "media_id": media_id,
                "safe": 0
            }
        },
        timeout=30,
        verify=False
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
            print(f"💬 你应该能在企业微信中看到文件附件了")
            print(f"\n💡 提示:")
            print(f"   - 文件以附件形式发送")
            print(f"   - 用户可以直接下载/转发")
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
