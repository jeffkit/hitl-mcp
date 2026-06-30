---
layout: home

hero:
  name: hitl-mcp
  text: 让 AI 在执行前先问你
  tagline: 一个 MCP 服务，让 AI Agent 能通过微信 / 企业微信向你发消息、等回复，实现 Human-in-the-Loop 审批与确认。
  actions:
    - theme: brand
      text: 5 分钟快速开始
      link: /guide/quickstart
    - theme: alt
      text: 选个引擎
      link: /guide/intro

features:
  - title: 微信 ClawBot 引擎
    details: 用个人微信扫码登录即可，AI 可向你发消息并等你回复。适合个人开发者。
    link: /engines/ilink
    linkText: 查看 iLink 引擎 →
  - title: 企微 AI 机器人引擎
    details: 接入企业微信智能机器人（AI Bot），团队协作、群聊确认两不误。
    link: /engines/wecom-aibot
    linkText: 查看企微引擎 →
  - title: 跨平台一键安装
    details: hitl-server 提供 Homebrew / deb / rpm 预构建产物，本地运行无需公网 IP，npx 拉起 MCP。
    link: /guide/hitl-server
    linkText: 安装 hitl-server →
  - title: Agent 可读的 Skill
    details: 内置一份安装向导 Skill，Cursor / Claude 等 Agent 读取后自动帮你装好并验证收消息。
    link: /skill/skill
    linkText: 查看 Skill →
---

## 通过 Agent 一键安装

不想自己一步步配？让你的 Agent（Cursor / Claude）读一下下面的向导页，它会自动帮你装好 hitl-server、启用引擎、写好 MCP 配置，并验证你的手机真的能收到消息：

> 请读取 https://jeffkit.github.io/hitl-mcp/skill/skill ，帮我安装并配置 hitl-mcp，验证能收到消息。

复制上面这句话发给你的 Agent 即可。[查看向导详情 →](/skill/skill)

