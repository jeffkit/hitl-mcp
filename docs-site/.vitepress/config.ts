import { defineConfig } from 'vitepress'

export default defineConfig({
  lang: 'zh-CN',
  title: 'hitl-mcp',
  description: '让 AI Agent 在执行关键操作前，通过微信 / 企业微信向你确认 — Human-in-the-Loop MCP',

  // GitHub Pages 项目站点：https://jeffkit.github.io/hitl-mcp/
  base: '/hitl-mcp/',
  cleanUrls: true,
  lastUpdated: true,

  // 忽略本地管理台地址（http://localhost:8081/console）被误判为死链
  // 同时忽略 public/SKILL.md（构建时拷贝到站点根，但死链检查不识别 public 资源）
  ignoreDeadLinks: [
    /^https?:\/\/localhost/,
    /^https?:\/\/127\.0\.0\.1/,
    /^\/hitl-mcp\/SKILL(\.md)?$/,
    /^\/SKILL(\.md)?$/,
  ],

  head: [
    ['meta', { name: 'theme-color', content: '#3c8c54' }],
    ['meta', { property: 'og:title', content: 'hitl-mcp · 让 AI 在执行前先问你' }],
    ['meta', { property: 'og:description', content: 'Human-in-the-Loop MCP，支持微信 ClawBot 与企业微信 AI 机器人。' }],
  ],

  themeConfig: {
    siteTitle: 'hitl-mcp',

    nav: [
      { text: '指南', link: '/guide/intro' },
      { text: '引擎', items: [
        { text: '微信 ClawBot（iLink）', link: '/engines/ilink' },
        { text: '企微 AI 机器人（wecom-aibot）', link: '/engines/wecom-aibot' },
      ]},
      { text: 'Agent Skill', link: '/skill/skill' },
      { text: 'GitHub', link: 'https://github.com/jeffkit/hitl-mcp' },
    ],

    sidebar: {
      '/guide/': [
        {
          text: '入门',
          items: [
            { text: '什么是 hitl-mcp', link: '/guide/intro' },
            { text: '整体架构', link: '/guide/architecture' },
            { text: '5 分钟快速开始', link: '/guide/quickstart' },
          ],
        },
        {
          text: '部署与配置',
          items: [
            { text: '本地安装 hitl-server', link: '/guide/hitl-server' },
            { text: '配置 MCP 客户端', link: '/guide/mcp-config' },
            { text: 'MCP 工具说明', link: '/guide/tools' },
            { text: '常见问题', link: '/guide/faq' },
          ],
        },
        {
          text: '使用方法',
          items: [
            { text: '让 AI 边做边问你（with-feedback）', link: '/guide/usage' },
          ],
        },
      ],
      '/engines/': [
        {
          text: '引擎',
          items: [
            { text: '微信 ClawBot（iLink）', link: '/engines/ilink' },
            { text: '企微 AI 机器人（wecom-aibot）', link: '/engines/wecom-aibot' },
          ],
        },
      ],
      '/skill/': [
        {
          text: 'Agent Skill',
          items: [
            { text: '一键安装 Skill', link: '/skill/skill' },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/jeffkit/hitl-mcp' },
    ],

    outline: { level: [2, 3], label: '本页内容' },

    docFooter: {
      prev: '上一页',
      next: '下一页',
    },

    lastUpdatedText: '最后更新',

    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            displayDetails: '查看详情',
            resetButtonTitle: '清除条件',
            backButtonTitle: '返回',
            noResultsText: '没有结果',
            footer: {
              selectText: '选择',
              navigateText: '切换',
              closeText: '关闭',
            },
          },
        },
      },
    },

    footer: {
      message: '基于 MIT 协议发布',
      copyright: 'Copyright © 2024-present hitl-mcp',
    },
  },
})
