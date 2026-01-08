"""
示例: 通过 HIL-MCP 发送 Markdown 文档内容

这是最简单的方式,企业微信会自动渲染 Markdown 格式
"""
import requests

# HIL Server 地址
HIL_SERVER_URL = "http://localhost:8081"

# 读取 MD 文件内容
with open("test_document.md", "r", encoding="utf-8") as f:
    md_content = f.read()

# 发送消息(使用 Markdown 类型)
response = requests.post(
    f"{HIL_SERVER_URL}/api/send-message",
    json={
        "message": md_content,
        "chat_id": "your_chat_id",  # 替换为实际的 chat_id
        "chat_type": "group",
        "timeout": 1200  # 20分钟超时
    }
)

print(f"发送结果: {response.json()}")

# 等待用户回复
session_id = response.json().get("session_id")
if session_id:
    print(f"会话ID: {session_id}, 等待用户回复...")

    # 轮询等待回复
    import time
    for i in range(20):  # 最多等待20次
        time.sleep(10)
        poll_response = requests.get(
            f"{HIL_SERVER_URL}/api/poll/{session_id}"
        ).json()

        if poll_response.get("has_reply"):
            print(f"收到回复: {poll_response.get('reply')}")
            break
