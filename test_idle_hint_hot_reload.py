#!/usr/bin/env python3
"""
测试空闲提示消息配置的热更新功能

验证修改 JSON 配置文件后，下次调用时能立即生效（无需重启服务）
"""
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_hot_reload():
    """测试热更新功能"""
    from hil_server.idle_hint_config import IdleHintConfigManager
    
    print("=" * 60)
    print("空闲提示消息配置热更新功能测试")
    print("=" * 60)
    
    # 使用临时配置文件
    test_config_file = project_root / "data" / "test_idle_hint_config.json"
    test_config_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 清理旧的测试文件
    if test_config_file.exists():
        test_config_file.unlink()
    
    print(f"\n✓ 使用测试配置文件: {test_config_file}")
    
    # 创建配置管理器实例
    config_manager = IdleHintConfigManager(test_config_file)
    
    # 测试 1: 读取初始配置
    print("\n[测试 1] 读取初始默认配置")
    message1 = config_manager.format_message(
        chat_id="test123",
        user_name="张三",
        chat_type="群聊",
        timestamp="14:30:00"
    )
    print(f"初始消息长度: {len(message1)} 字符")
    assert "张三" in message1
    assert "test123" in message1
    print("✓ 初始配置读取成功")
    
    # 测试 2: 修改配置文件（模拟用户在管理台修改）
    print("\n[测试 2] 模拟用户修改配置")
    new_template = "你好 {user_name}！\n\nChat ID: {chat_id}\n时间: {timestamp}"
    result = config_manager.update_default_config(
        template=new_template,
        enabled=True,
        updated_by="test_user"
    )
    assert result["success"]
    print(f"✓ 配置已更新: {result['message']}")
    
    # 测试 3: 立即读取新配置（无需重启）
    print("\n[测试 3] 立即读取新配置（热更新）")
    message2 = config_manager.format_message(
        chat_id="test456",
        user_name="李四",
        chat_type="私聊",
        timestamp="15:00:00"
    )
    print(f"新消息: {message2}")
    assert "你好 李四" in message2
    assert "Chat ID: test456" in message2
    assert "15:00:00" in message2
    assert message2 != message1  # 确保消息已更改
    print("✓ 热更新生效，配置立即应用")
    
    # 测试 4: 添加 Chat ID 特定配置
    print("\n[测试 4] 添加 Chat ID 特定配置")
    chat_template = "特殊消息：{user_name} 在 {chat_id}"
    result = config_manager.update_chat_config(
        chat_id="special_chat",
        template=chat_template,
        enabled=True,
        updated_by="test_user"
    )
    assert result["success"]
    print(f"✓ Chat ID 配置已添加: {result['message']}")
    
    # 测试 5: 验证 Chat ID 特定配置优先级
    print("\n[测试 5] 验证 Chat ID 特定配置优先级")
    message3 = config_manager.format_message(
        chat_id="special_chat",
        user_name="王五",
        chat_type="群聊",
        timestamp="16:00:00"
    )
    print(f"特定配置消息: {message3}")
    assert "特殊消息：王五" in message3
    assert "special_chat" in message3
    print("✓ Chat ID 特定配置优先级正确")
    
    # 测试 6: 禁用配置
    print("\n[测试 6] 测试禁用配置")
    result = config_manager.update_default_config(
        template=new_template,
        enabled=False,  # 禁用
        updated_by="test_user"
    )
    assert result["success"]
    
    message4 = config_manager.format_message(
        chat_id="test789",
        user_name="赵六",
        chat_type="群聊",
        timestamp="17:00:00"
    )
    assert message4 is None  # 禁用后返回 None
    print("✓ 禁用配置功能正常")
    
    # 测试 7: 删除 Chat ID 配置
    print("\n[测试 7] 删除 Chat ID 配置")
    result = config_manager.delete_chat_config("special_chat")
    assert result["success"]
    print(f"✓ 配置已删除: {result['message']}")
    
    # 测试 8: 验证多次配置变更
    print("\n[测试 8] 快速多次修改配置（模拟实际使用）")
    for i in range(3):
        template = f"版本 {i+1}: {{user_name}} @ {{chat_id}}"
        config_manager.update_default_config(
            template=template,
            enabled=True,
            updated_by=f"user_{i}"
        )
        
        message = config_manager.format_message(
            chat_id=f"chat_{i}",
            user_name=f"用户{i}",
            chat_type="群聊",
            timestamp=f"18:0{i}:00"
        )
        
        assert f"版本 {i+1}" in message
        print(f"  ✓ 版本 {i+1} 配置生效")
    
    print("\n✓ 多次配置变更测试通过")
    
    # 清理测试文件
    print("\n[清理] 删除测试配置文件")
    if test_config_file.exists():
        test_config_file.unlink()
    print("✓ 测试文件已清理")
    
    print("\n" + "=" * 60)
    print("🎉 所有热更新测试通过！")
    print("=" * 60)
    print("\n功能验证成功：")
    print("1. ✓ 配置文件读取")
    print("2. ✓ 配置修改立即生效（热更新）")
    print("3. ✓ Chat ID 特定配置")
    print("4. ✓ 配置优先级")
    print("5. ✓ 启用/禁用功能")
    print("6. ✓ 配置删除")
    print("7. ✓ 多次快速修改")
    print("\n✅ 配置修改后无需重启服务即可生效！")


def test_concurrent_reads():
    """测试并发读取配置"""
    from hil_server.idle_hint_config import idle_hint_config
    import threading
    
    print("\n" + "=" * 60)
    print("并发读取测试")
    print("=" * 60)
    
    results = []
    errors = []
    
    def read_config(thread_id):
        try:
            for i in range(10):
                message = idle_hint_config.format_message(
                    chat_id=f"chat_{thread_id}_{i}",
                    user_name=f"用户{thread_id}",
                    chat_type="群聊"
                )
                if message:
                    results.append((thread_id, i))
        except Exception as e:
            errors.append((thread_id, str(e)))
    
    # 创建多个线程并发读取
    threads = []
    for i in range(5):
        thread = threading.Thread(target=read_config, args=(i,))
        threads.append(thread)
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    print(f"✓ 完成 {len(results)} 次并发读取")
    if errors:
        print(f"✗ 发现 {len(errors)} 个错误:")
        for thread_id, error in errors:
            print(f"  - 线程 {thread_id}: {error}")
        return False
    else:
        print("✓ 无错误")
        print("✅ 并发读取测试通过")
        return True


if __name__ == "__main__":
    try:
        test_hot_reload()
        test_concurrent_reads()
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！配置热更新功能运行正常。")
        print("=" * 60)
        sys.exit(0)
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 测试失败")
        print("=" * 60)
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
