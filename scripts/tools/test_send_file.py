#!/usr/bin/env python3
"""
测试脚本: 发送 MD 文件到企业微信

演示三种方式:
1. 发送 Markdown 内容(推荐 - 当前支持)
2. 上传并发送文件(需要扩展)
3. 直接使用 fly-pigeon 发送文件
"""

import requests
import sys
from pathlib import Path

# ==================== 配置 ====================
HIL_SERVER_URL = "http://localhost:8081"  # HIL Server 地址
CHAT_ID = "your_chat_id"  # 替换为实际的群/私聊 ID
BOT_KEY = "your_bot_key"  # Direct 模式需要(如果使用 Relay 模式则不需要)

# 测试文件路径
MD_FILE = Path(__file__).parent / "test_document.md"


# ==================== 方式1: 发送 Markdown 内容 ====================
def send_markdown_content():
    """
    方式1: 读取 MD 文件内容,以 Markdown 格式发送

    优点:
    - ✅ 当前已支持,无需修改代码
    - ✅ 企业微信会渲染成漂亮格式
    - ✅ 支持所有 Markdown 语法

    缺点:
    - ❌ 发送的是内容,不是文件附件
    - ❌ 用户无法直接下载 MD 文件
    """
    print("\n" + "="*60)
    print("方式1: 发送 Markdown 内容")
    print("="*60)

    # 读取 MD 文件内容
    if not MD_FILE.exists():
        print(f"❌ 文件不存在: {MD_FILE}")
        return False

    md_content = MD_FILE.read_text(encoding="utf-8")

    print(f"📄 读取文件: {MD_FILE}")
    print(f"📝 内容长度: {len(md_content)} 字符")
    print(f"📋 内容预览:\n{md_content[:200]}...")

    # 发送消息
    try:
        response = requests.post(
            f"{HIL_SERVER_URL}/api/send-message",
            json={
                "message": md_content,
                "chat_id": CHAT_ID,
                "chat_type": "group",
                "timeout": 1200,  # 20分钟
                "wait_reply": True
            },
            timeout=10
        )

        result = response.json()

        if result.get("success"):
            session_id = result.get("session_id")
            print(f"✅ 发送成功!")
            print(f"🆔 会话ID: {session_id}")
            print(f"💡 提示: 企业微信会渲染 Markdown 格式")
            return True
        else:
            print(f"❌ 发送失败: {result.get('error')}")
            return False

    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False


# ==================== 方式2: 上传并发送文件(扩展方案) ====================
def send_file_attachment():
    """
    方式2: 上传文件并发送文件附件

    优点:
    - ✅ 发送的是真实的文件附件
    - ✅ 用户可以直接下载/转发
    - ✅ 支持任意文件格式

    缺点:
    - ❌ 需要扩展 HIL Server 代码
    - ❌ 需要调用企业微信上传接口获取 media_id
    """
    print("\n" + "="*60)
    print("方式2: 上传并发送文件附件(需要扩展)")
    print("="*60)

    print("⚠️  此功能需要先扩展 HIL Server 代码")
    print("📖 请参考 add_file_support.patch 中的实现步骤")
    print("\n实现步骤:")
    print("  1. 添加 /api/upload-file 接口")
    print("  2. 在 sender.py 中添加 msg_type='file' 支持")
    print("  3. 在 Worker 中实现文件上传处理")
    print("  4. 测试 fly-pigeon 是否支持 file() 方法")

    # 伪代码示例
    print("\n📝 预期代码示例:")
    print("""
    # 步骤1: 上传文件
    response = requests.post(
        f"{HIL_SERVER_URL}/api/upload-file",
        files={"file": open("test_document.md", "rb")}
    )
    media_id = response.json()["media_id"]

    # 步骤2: 发送文件消息
    response = requests.post(
        f"{HIL_SERVER_URL}/api/send-message",
        json={
            "chat_id": CHAT_ID,
            "files": {"media_id": media_id, "safe": 0},
            "wait_reply": True
        }
    )
    """)

    return False


# ==================== 方式3: 直接使用 fly-pigeon ====================
def send_with_pigeon_directly():
    """
    方式3: 绕过 HIL Server,直接使用 fly-pigeon 发送文件

    优点:
    - ✅ 直接调用,性能最好
    - ✅ 可以测试 fly-pigeon 是否支持文件

    缺点:
    - ❌ 无法使用 HIL 的会话管理
    - ❌ 无法等待用户回复
    - ❌ 需要 BOT_KEY
    """
    print("\n" + "="*60)
    print("方式3: 直接使用 fly-pigeon (测试)")
    print("="*60)

    try:
        from pigeon import Bot

        bot = Bot(bot_key=BOT_KEY)

        print(f"🔧 Bot 对象创建成功")
        print(f"📋 支持的方法:")

        # 检查支持的方法
        methods = [m for m in dir(bot) if not m.startswith('_') and callable(getattr(bot, m))]
        for method in sorted(methods):
            print(f"   - {method}()")

        # 检查是否有 file 方法
        if hasattr(bot, 'file'):
            print(f"\n✅ bot.file() 方法存在!")

            # 尝试上传文件 (需要先实现)
            print(f"⚠️  但是需要先实现文件上传获取 media_id")
            print(f"📖 请查看企业微信 API 文档:")
            print(f"   https://developer.work.weixin.qq.com/document/path/95098")

        else:
            print(f"\n❌ bot.file() 方法不存在")
            print(f"💡 建议使用方式1(Markdown 内容)发送")

        return False

    except ImportError:
        print(f"❌ 无法导入 pigeon 包")
        print(f"💡 请在腾讯内网环境安装:")
        print(f"   pip install fly-pigeon")
        return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


# ==================== 主函数 ====================
def main():
    """主函数"""
    print("="*60)
    print("MD 文件发送测试")
    print("="*60)
    print(f"📁 测试文件: {MD_FILE}")
    print(f"🌐 HIL Server: {HIL_SERVER_URL}")
    print(f"💬 Chat ID: {CHAT_ID}")

    if CHAT_ID == "your_chat_id":
        print("\n⚠️  请先修改脚本中的 CHAT_ID 为实际的群/私聊 ID")
        sys.exit(1)

    # 三种方式测试
    print("\n请选择测试方式:")
    print("  1. 发送 Markdown 内容(推荐 - 当前支持)")
    print("  2. 上传并发送文件附件(需要扩展)")
    print("  3. 直接使用 fly-pigeon(测试)")
    print("  0. 退出")

    choice = input("\n请输入选择 (0-3): ").strip()

    if choice == "1":
        success = send_markdown_content()
    elif choice == "2":
        success = send_file_attachment()
    elif choice == "3":
        success = send_with_pigeon_directly()
    elif choice == "0":
        print("👋 退出")
        return
    else:
        print("❌ 无效选择")
        return

    print("\n" + "="*60)
    if success:
        print("✅ 测试完成")
    else:
        print("⚠️  请查看上面的输出信息")
    print("="*60)


if __name__ == "__main__":
    main()
