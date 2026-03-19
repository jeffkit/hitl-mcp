#!/usr/bin/env python3
"""
Forward Service 多 Bot 功能测试

测试：
1. Bot Key 提取
2. Bot 配置查找
3. 访问控制
4. 默认 Bot 回退
"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from forward_service.config_v2 import config_v2

def test_bot_key_extraction():
    """测试 Bot Key 提取"""
    print("🧪 测试 1: Bot Key 提取")
    
    webhook_url = "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<YOUR_BOT_KEY>"
    bot_key = config_v2.extract_bot_key_from_webhook_url(webhook_url)
    
    assert bot_key == "<YOUR_BOT_KEY>", f"提取失败: {bot_key}"
    print(f"  ✅ 提取成功: {bot_key}")
    print("")

def test_bot_lookup():
    """测试 Bot 配置查找"""
    print("🧪 测试 2: Bot 配置查找")
    
    # 查找存在的 Bot
    bot = config_v2.get_bot("<YOUR_BOT_KEY>")
    assert bot is not None, "应该找到 Bot"
    assert bot.name == "默认测试机器人", f"Bot 名称错误: {bot.name}"
    print(f"  ✅ 找到 Bot: {bot.name}")
    
    # 查找不存在的 Bot
    bot = config_v2.get_bot("non_existent_key")
    assert bot is None, "不应该找到 Bot"
    print(f"  ✅ 不存在的 Bot 返回 None")
    print("")

def test_bot_or_default():
    """测试默认 Bot 回退"""
    print("🧪 测试 3: 默认 Bot 回退")
    
    # 不存在的 Bot，应该返回默认 Bot
    bot = config_v2.get_bot_or_default("non_existent_key")
    assert bot is not None, "应该返回默认 Bot"
    assert bot.bot_key == config_v2.default_bot_key, f"应该是默认 Bot: {bot.bot_key}"
    print(f"  ✅ 回退到默认 Bot: {bot.name}")
    print("")

def test_access_control():
    """测试访问控制"""
    print("🧪 测试 4: 访问控制")
    
    # 测试 allow_all 模式
    bot = config_v2.get_bot("<YOUR_BOT_KEY>")
    allowed, reason = config_v2.check_access(bot, "any_user")
    assert allowed, "allow_all 模式应该允许所有用户"
    print(f"  ✅ allow_all 模式: 允许访问")
    
    # 测试 whitelist 模式
    bot = config_v2.get_bot("test_bot_key_2")
    
    # 在白名单中
    allowed, reason = config_v2.check_access(bot, "T15500028A")
    assert allowed, "白名单用户应该被允许"
    print(f"  ✅ whitelist 模式: 白名单用户允许访问")
    
    # 不在白名单中
    allowed, reason = config_v2.check_access(bot, "other_user")
    assert not allowed, "非白名单用户应该被拒绝"
    print(f"  ✅ whitelist 模式: 非白名单用户拒绝访问")
    print(f"     原因: {reason}")
    print("")

def test_forward_config():
    """测试转发配置"""
    print("🧪 测试 5: 转发配置")
    
    bot = config_v2.get_bot("<YOUR_BOT_KEY>")
    url = bot.forward_config.get_url()
    assert url == "https://httpbin.org/post", f"URL 错误: {url}"
    print(f"  ✅ URL 生成正确: {url}")
    
    # 测试带 agent_id 的 URL
    bot = config_v2.get_bot("test_bot_key_2")
    url = bot.forward_config.get_url()
    assert url == "https://httpbin.org/post", f"URL 错误: {url}"
    print(f"  ✅ URL 生成正确: {url}")
    print("")

def test_config_dict():
    """测试配置字典"""
    print("🧪 测试 6: 配置字典")
    
    config_dict = config_v2.get_config_dict()
    assert "default_bot_key" in config_dict
    assert "bots" in config_dict
    assert len(config_dict["bots"]) == 2
    print(f"  ✅ 配置字典正确")
    print(f"     默认 Bot Key: {config_dict['default_bot_key']}")
    print(f"     Bot 数量: {len(config_dict['bots'])}")
    print("")

def main():
    """运行所有测试"""
    print("=" * 50)
    print("Forward Service 多 Bot 功能测试")
    print("=" * 50)
    print("")
    
    try:
        test_bot_key_extraction()
        test_bot_lookup()
        test_bot_or_default()
        test_access_control()
        test_forward_config()
        test_config_dict()
        
        print("=" * 50)
        print("✅ 所有测试通过！")
        print("=" * 50)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
