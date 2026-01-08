# 测试文档 📝

这是一个测试 Markdown 文件,用于演示企业微信文件发送功能。

## 功能特性

- ✅ 支持纯文本消息
- ✅ 支持 Markdown 格式
- ✅ 支持图片消息
- 🔧 文件消息(待实现)

## 代码示例

```python
# 发送 Markdown 消息
from pigeon import Bot

bot = Bot(bot_key="your_bot_key")
bot.markdown(
    chat_id="your_chat_id",
    msg_content="# Hello\n\n这是 Markdown 内容"
)
```

## 文件格式

企业微信支持发送以下类型的文件:

| 类型 | 格式示例 |
|------|----------|
| 文档 | MD, TXT, PDF, DOC, DOCX |
| 表格 | XLS, XLSX, CSV |
| 演示 | PPT, PPTX |
| 压缩 | ZIP, RAR, TAR |
| 代码 | PY, JS, TS, JSON |

---

**创建时间**: 2026-01-08
**测试环境**: HIL-MCP 项目
