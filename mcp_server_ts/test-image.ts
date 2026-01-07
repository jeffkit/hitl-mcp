/**
 * 图片功能测试脚本
 * 
 * 测试：
 * 1. 上传图片
 * 2. 发送带图片的消息
 * 3. 接收带图片的回复
 */

import { setConfig, createConfig } from './src/config.js';
import { WeComClient } from './src/wecom-client.js';
import { existsSync } from 'fs';

async function testImageFeatures() {
  console.log('🖼️  测试图片功能...\n');

  // 配置测试环境
  const config = createConfig({
    serviceUrl: 'https://hitl.woa.com/api',
    defaultChatId: 'wokSFfCgAAimChUpCX7QnUR8_mlwkU3A',
    defaultProjectName: 'test-image',
    defaultTimeout: 3600,
  });
  setConfig(config);

  const client = new WeComClient();

  // 测试图片路径（使用小图片避免 413 错误）
  const imagePath = '/Users/kongjie/projects/hil-mcp/test-small.png';
  
  if (!existsSync(imagePath)) {
    console.log(`❌ 图片文件不存在: ${imagePath}`);
    process.exit(1);
  }

  console.log(`📁 找到测试图片: ${imagePath}\n`);

  // 测试 1: 上传图片
  console.log('📤 测试 1: 上传图片');
  let imageUrl: string;
  try {
    const result = await client.uploadImage(imagePath);
    
    if (result.success && result.image_url) {
      console.log('✅ 图片上传成功');
      console.log(`   URL: ${result.image_url}\n`);
      imageUrl = result.image_url;
    } else {
      console.log('❌ 图片上传失败');
      console.log(`   错误: ${result.error}\n`);
      process.exit(1);
    }
  } catch (error) {
    console.log('❌ 测试失败:', error);
    process.exit(1);
  }

  // 测试 2: 发送带图片的消息并等待回复
  console.log('📤 测试 2: 发送带图片的消息并等待回复');
  try {
    const result = await client.sendMessage({
      message: '🖼️  测试图片功能\n\n请回复：\n1. 文本内容：收到图片\n2. 附带一张图片\n\n（60秒超时）',
      chat_id: config.defaultChatId,
      project_name: config.defaultProjectName,
      images: [imageUrl],
      timeout: 60,  // 60 秒超时
      wait_reply: true,
    });
    
    if (!result.success) {
      console.log('❌ 发送失败');
      console.log(`   错误: ${result.error}\n`);
      process.exit(1);
    }

    console.log('✅ 消息（带图片）发送成功');
    console.log(`   Session ID: ${result.session_id}\n`);

    const sessionId = result.session_id!;

    // 轮询等待回复
    console.log('⏳ 等待用户回复（60秒超时）...');
    console.log('   请回复文本 + 图片\n');
    
    const startTime = Date.now();
    const timeout = 60000;
    const pollInterval = 2000;

    let replyReceived = false;
    while (Date.now() - startTime < timeout) {
      try {
        const pollResult = await client.pollReplies(sessionId);
        
        if (pollResult.has_reply) {
          console.log('✅ 收到用户回复！\n');
          console.log(`   回复数量: ${pollResult.replies.length}`);
          
          let hasText = false;
          let hasImage = false;
          
          pollResult.replies.forEach((reply, index) => {
            console.log(`\n   --- 回复 ${index + 1} ---`);
            console.log(`   类型: ${reply.msg_type}`);
            console.log(`   用户: ${reply.from_user.name} (@${reply.from_user.alias})`);
            console.log(`   时间: ${reply.timestamp}`);
            
            if (reply.msg_type === 'text') {
              console.log(`   文本内容: ${reply.content}`);
              hasText = true;
            } else if (reply.msg_type === 'image') {
              // @ts-ignore
              const imageUrl = reply.image_url || (reply as any).content;
              console.log(`   图片URL: ${imageUrl}`);
              hasImage = true;
            } else {
              console.log(`   原始内容: ${JSON.stringify(reply, null, 2)}`);
            }
          });
          
          console.log('\n📊 回复分析:');
          console.log(`   包含文本: ${hasText ? '✅' : '❌'}`);
          console.log(`   包含图片: ${hasImage ? '✅' : '❌'}`);
          
          if (hasText && hasImage) {
            console.log('\n🎉 图片功能测试完全通过！');
          } else if (hasText || hasImage) {
            console.log('\n⚠️  部分功能正常，但未收到文本+图片的完整回复');
          } else {
            console.log('\n⚠️  未识别到文本或图片回复');
          }
          
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
      console.log('\n⏰ 等待超时');
      await client.markTimeout(sessionId);
    }

    console.log('');
  } catch (error) {
    console.log('❌ 测试失败:', error);
    process.exit(1);
  }

  console.log('📝 测试完成\n');
}

// 运行测试
testImageFeatures().catch(error => {
  console.error('测试失败:', error);
  process.exit(1);
});
