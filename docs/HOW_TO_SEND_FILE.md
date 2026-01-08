# 如何发送 MD 文件到企业微信

我为你创建了完整的演示和实现方案。请根据你的需求选择合适的方式。

---

## 📦 相关文件

| 文件 | 说明 |
|------|------|
| `test_document.md` | 测试用的 MD 文档 |
| `quick_send.py` | 快速发送脚本(推荐) |
| `send_markdown_example.py` | 详细示例代码 |
| `test_send_file.py` | 完整测试脚本(3种方式) |
| `add_file_support.patch` | 文件发送功能扩展补丁 |

---

## 🚀 方式1: 发送 Markdown 内容(推荐)

这是**最简单且当前已支持**的方式。

### 特点
- ✅ 无需修改代码,直接可用
- ✅ 企业微信会自动渲染 Markdown 格式
- ✅ 支持标题、列表、代码、表格等所有 Markdown 语法
- ❌ 发送的是内容,不是文件附件

### 使用步骤

#### 1. 修改配置

编辑 `quick_send.py`,修改 `CHAT_ID`:

```python
CHAT_ID = "your_chat_id"  # 改为实际的群/私聊 ID
```

#### 2. 运行脚本

```bash
python quick_send.py
```

#### 3. 效果示例

发送的 MD 内容:

```
# 测试文档 📝

这是一个测试 Markdown 文件,用于演示企业微信文件发送功能。

## 功能特性

- ✅ 支持纯文本消息
- ✅ 支持 Markdown 格式
```

企业微信会渲染成:

> # **测试文档** 📝
>
> 这是一个测试 Markdown 文件,用于演示企业微信文件发送功能。
>
> ## 功能特性
>
> - ✅ 支持纯文本消息
> - ✅ 支持 Markdown 格式

---

## 🔧 方式2: 扩展文件发送功能

如果你需要发送**真实的文件附件**(让用户可以下载),需要扩展代码。

### 实现步骤

#### 1. 添加文件上传 API

在 `packages/hil-server/hil_server/handlers/api.py` 中添加:

```python
@router.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    """上传文件到企业微信"""
    from pigeon import Bot
    bot = Bot(bot_key=config.bot_key)

    # 上传文件获取 media_id
    result = bot.upload_file(
        file_content=await file.read(),
        filename=file.filename
    )

    return {"media_id": result["media_id"]}
```

#### 2. 添加文件消息支持

在 `packages/hil-server/hil_server/sender.py` 中添加:

```python
elif msg_type == "file":
    result = bot.file(
        chat_id=chat_id,
        media_id=files["media_id"],
        safe=files.get("safe", 0)
    )
```

#### 3. Worker 中实现文件上传

在 `packages/devcloud-worker/devcloud_worker/sender.py` 中添加:

```python
async def handle_upload_file(payload: dict) -> dict:
    """处理上传文件请求"""
    from pigeon import Bot
    bot = Bot(bot_key=config.bot_key)

    import base64
    content = base64.b64decode(payload["content"])

    result = bot.upload_file(
        file_content=content,
        filename=payload["filename"]
    )

    return {"media_id": result["media_id"]}
```

#### 4. 使用示例

```python
# 步骤1: 上传文件
response = requests.post(
    "http://localhost:8081/api/upload-file",
    files={"file": open("test_document.md", "rb")}
)
media_id = response.json()["media_id"]

# 步骤2: 发送文件消息
response = requests.post(
    "http://localhost:8081/api/send-message",
    json={
        "chat_id": CHAT_ID,
        "files": {"media_id": media_id, "safe": 0},
        "wait_reply": True
    }
)
```

---

## 🧪 方式3: 测试 fly-pigeon 支持

检查 fly-pigeon 是否原生支持文件发送:

```python
from pigeon import Bot

bot = Bot(bot_key="your_key")

# 检查支持的方法
methods = [m for m in dir(bot) if not m.startswith('_')]
print("支持的方法:", methods)

# 如果有 file 方法,尝试使用
if hasattr(bot, 'file'):
    # 需要先上传文件获取 media_id
    bot.file(chat_id="...", media_id="...", safe=0)
```

---

## 📊 三种方式对比

| 方式 | 优点 | 缺点 | 推荐场景 |
|------|------|------|----------|
| **方式1: Markdown 内容** | 简单、当前支持、渲染效果好 | 不是文件附件 | 发送文档内容、代码示例 |
| **方式2: 文件附件** | 真实文件、可下载转发 | 需要扩展代码 | 分发文件、需要保存 |
| **方式3: 直接调用** | 性能最好 | 无会话管理 | 测试、直连场景 |

---

## 💡 企业微信文件 API 说明

根据企业微信官方文档,文件消息支持:

### 文件类型
- 📄 文档: TXT, PDF, DOC, DOCX, HTML, MD 等
- 📊 表格: XLS, XLSX, CSV
- 📽 演示: PPT, PPTX
- 📦 压缩: ZIP, RAR, TAR 等
- 💻 代码: PY, JS, TS, JSON 等

### API 调用流程

```json
{
  "msgtype": "file",
  "file": {
    "media_id": "文件ID",
    "safe": 0
  }
}
```

其中 `media_id` 需要先通过上传接口获取。

---

## ✅ 快速开始

### 现在就可以测试(方式1):

```bash
# 1. 修改 quick_send.py 中的 CHAT_ID
# 2. 运行脚本
python quick_send.py
```

### 如果需要文件附件功能(方式2):

```bash
# 参考 add_file_support.patch 中的实现步骤
# 需要修改 3 个文件:
#   - packages/hil-server/hil_server/handlers/api.py
#   - packages/hil-server/hil_server/sender.py
#   - packages/devcloud-worker/devcloud_worker/sender.py
```

---

## 🆘 常见问题

### Q1: 为什么不直接用文件附件?

**A:** Markdown 方式更简单,当前已支持,且渲染效果更好。如果确实需要文件附件,可以扩展代码。

### Q2: fly-pigeon 支持文件发送吗?

**A:** fly-pigeon 是腾讯内部包,很可能支持,但需要查看文档或源码确认。方式3的测试脚本可以帮你检查。

### Q3: 如何获取 Chat ID?

**A:**
1. 在企业微信中打开群聊
2. 发送消息: `chat_id`
3. HIL Server 会自动回复你的 Chat ID

### Q4: 文件大小限制?

**A:** 企业微信限制:
- 图片: 10MB
- 视频: 10MB
- 文件: 建议不超过 20MB

---

## 📞 需要帮助?

如果有任何问题,可以:
1. 查看 `test_send_file.py` 中的完整示例
2. 参考 `add_file_support.patch` 中的实现
3. 检查企业微信官方文档

祝你使用愉快! 🎉
