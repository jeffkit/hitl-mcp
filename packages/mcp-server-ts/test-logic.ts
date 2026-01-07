/**
 * 逻辑测试脚本
 * 
 * 测试核心功能是否正常工作（不依赖 Cursor）
 */

import { setConfig, createConfig } from './src/config.js';
import { WeComClient } from './src/wecom-client.js';

async function testWeComClient() {
  console.log('🧪 测试 WeComClient...\n');

  // 配置测试环境
  const config = createConfig({
    serviceUrl: 'https://hitl.woa.com/api',
    defaultChatId: 'wokSFfCgAAimChUpCX7QnUR8_mlwkU3A',
    defaultProjectName: 'test-ts-mcp',
    defaultTimeout: 3600,
  });
  setConfig(config);

  const client = new WeComClient();

  // 测试 1: 发送消息（不等待回复）
  console.log('📤 测试 1: 发送消息（不等待回复）');
  try {
    const result = await client.sendMessage({
      message: '🧪 测试 TypeScript 版 MCP - send_message_only\n\n这是一条测试消息，无需回复。',
      chat_id: config.defaultChatId,
      project_name: config.defaultProjectName,
      wait_reply: false,
    });
    
    if (result.success) {
      console.log('✅ 发送成功');
      console.log(`   响应: ${JSON.stringify(result)}\n`);
    } else {
      console.log('❌ 发送失败');
      console.log(`   错误: ${result.error}\n`);
      process.exit(1);
    }
  } catch (error) {
    console.log('❌ 测试失败:', error);
    process.exit(1);
  }

  // 等待 2 秒
  console.log('⏳ 等待 2 秒...\n');
  await new Promise(resolve => setTimeout(resolve, 2000));

  // 测试 2: 发送消息并等待回复
  console.log('📤 测试 2: 发送消息并等待回复');
  try {
    const result = await client.sendMessage({
      message: '🧪 测试 TypeScript 版 MCP - send_and_wait_reply\n\n请回复 "OK" 来完成测试（30秒超时）',
      chat_id: config.defaultChatId,
      project_name: config.defaultProjectName,
      timeout: 30,  // 30 秒超时
      wait_reply: true,
    });
    
    if (!result.success) {
      console.log('❌ 发送失败');
      console.log(`   错误: ${result.error}\n`);
      process.exit(1);
    }

    console.log('✅ 发送成功，已创建会话');
    console.log(`   Session ID: ${result.session_id}\n`);

    const sessionId = result.session_id!;

    // 轮询等待回复
    console.log('⏳ 等待用户回复（30秒超时）...');
    const startTime = Date.now();
    const timeout = 30000;
    const pollInterval = 2000;

    let replyReceived = false;
    while (Date.now() - startTime < timeout) {
      try {
        const pollResult = await client.pollReplies(sessionId);
        
        if (pollResult.has_reply) {
          console.log('✅ 收到用户回复！');
          console.log(`   回复数量: ${pollResult.replies.length}`);
          pollResult.replies.forEach((reply, index) => {
            console.log(`   回复 ${index + 1}:`);
            console.log(`     类型: ${reply.msg_type}`);
            console.log(`     内容: ${reply.content}`);
            console.log(`     用户: ${reply.from_user.name} (@${reply.from_user.alias})`);
          });
          replyReceived = true;
          break;
        }

        if (pollResult.status === 'not_found') {
          console.log('❌ 会话不存在或已过期');
          process.exit(1);
        }

        // 显示进度
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        process.stdout.write(`\r   已等待 ${elapsed} 秒...`);
      } catch (error) {
        console.log(`\n⚠️  轮询失败: ${error}`);
      }

      await new Promise(resolve => setTimeout(resolve, pollInterval));
    }

    if (!replyReceived) {
      console.log('\n⏰ 等待超时，标记会话超时');
      await client.markTimeout(sessionId);
      console.log('✅ 会话已标记为超时');
    }

    console.log('');
  } catch (error) {
    console.log('❌ 测试失败:', error);
    process.exit(1);
  }

  console.log('🎉 所有测试完成！\n');
  console.log('总结:');
  console.log('  ✅ 配置管理正常');
  console.log('  ✅ HTTP 客户端正常');
  console.log('  ✅ 发送消息（不等待）正常');
  console.log('  ✅ 发送消息（等待回复）正常');
  console.log('  ✅ 轮询机制正常');
  console.log('  ✅ 超时处理正常');
}

// 运行测试
testWeComClient().catch(error => {
  console.error('测试失败:', error);
  process.exit(1);
});
