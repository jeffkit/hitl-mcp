# Homebrew formula for HITL Server
# 用法（发布到 tap 仓库后）：
#   brew tap jeffkit/hitl
#   brew install hitl-server
# 或直接用本文件：
#   brew install --formula ./packaging/hitl-server.rb
#
# 说明：
#   - 安装预构建二进制（one-dir，含内嵌管理台）到 /opt/homebrew/opt/hitl-server
#   - 安装 launchd plist（开机自启 + 崩溃重启），默认监听 127.0.0.1:8081
#   - 数据目录 ~/.hitl（凭证持久化）；首次安装若存在 ~/.hil-mcp 会自动迁移
#   - 启动：brew services start hitl-server ；管理台：http://localhost:8081/console
class HitlServer < Formula
  desc "Human-in-the-Loop Server (iLink + WeCom AI, personal desktop)"
  homepage "https://github.com/jeffkit/hitl-mcp"
  # 发布时由 CI 注入真实 version / sha256 / 资源 URL
  version "2.1.0"
  # sha256 "REPLACE_WITH_RELEASE_SHA256"
  # on_macos do
  #   url "https://github.com/jeffkit/hitl-mcp/releases/download/hitl-server-v2.1.0/hitl-server-darwin-arm64.tar.gz"
  #   on_arm do
  #     sha256 "REPLACE_WITH_ARM64_SHA256"
  #   end
  #   on_intel do
  #     url "https://github.com/jeffkit/hitl-mcp/releases/download/hitl-server-v2.1.0/hitl-server-darwin-x86_64.tar.gz"
  #     sha256 "REPLACE_WITH_X86_64_SHA256"
  #   end
  # end

  # 上面 url/sha256 块由发版 CI 渲染。下面是本地源码构建兜底（若未提供预构建包）。
  depends_on "uv" => :build

  def install
    # 预构建二进制：解压即用
    if File.exist?("hitl-server/hitl-server")
      libexec.install Dir["hitl-server/*"]
      bin.install_symlink libexec/"hitl-server"
    else
      # 兜底：从源码构建（需在 tap 仓库内有源码）
      odie "未找到预构建二进制；请使用发版 CI 产出的 formula。"
    end
  end

  def plist
    <<~EOS
      <?xml version="1.0" encoding="UTF-8"?>
      <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
      <plist version="1.0">
      <dict>
        <key>Label</key><string>#{plist_name}</string>
        <key>ProgramArguments</key>
        <array>
          <string>#{opt_libexec}/hitl-server</string>
        </array>
        <key>WorkingDirectory</key><string>#{opt_libexec}</string>
        <key>EnvironmentVariables</key>
        <dict>
          <key>HITL_PORT</key><string>8081</string>
          <key>ENABLE_ILINK_ENGINE</key><string>true</string>
          <key>ILINK_BOT_KEY</key><string>ilink-bot-1</string>
          <key>ILINK_BASE_URL</key><string>https://ilinkai.weixin.qq.com</string>
          <key>HITL_HOME</key><string>#{Dir.home}/.hitl</string>
        </dict>
        <key>RunAtLoad</key><true/>
        <key>KeepAlive</key><true/>
        <key>StandardOutPath</key><string>#{Dir.home}/.hitl/logs/hitl-server.out.log</string>
        <key>StandardErrorPath</key><string>#{Dir.home}/.hitl/logs/hitl-server.err.log</string>
      </dict>
      </plist>
    EOS
  end

  def caveats
    <<~EOS
      HITL Server 已安装。启动：
        brew services start hitl-server
      管理台：http://localhost:8081/console  （默认账号 admin / 见文档）
      数据/凭证目录：~/.hitl
      卸载：brew uninstall hitl-server && brew services stop hitl-server
    EOS
  end

  test do
    assert_match "healthy", shell_output("#{bin}/hitl-server --help 2>&1 || true")
  end
end
