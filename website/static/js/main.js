// HITL-Walle 前端交互脚本

// 检查服务状态
async function checkServiceStatus() {
    const statusElement = document.getElementById('service-status');
    if (!statusElement) return;
    
    try {
        const response = await fetch('/health');
        const data = await response.json();
        
        if (data.status === 'healthy') {
            statusElement.classList.add('online');
            statusElement.classList.remove('offline');
            statusElement.querySelector('.status-text').textContent = '服务正常';
        } else {
            throw new Error('Service unhealthy');
        }
    } catch (error) {
        statusElement.classList.add('offline');
        statusElement.classList.remove('online');
        statusElement.querySelector('.status-text').textContent = '服务异常';
    }
}

// 页面加载时检查状态
window.addEventListener('load', checkServiceStatus);

// 每30秒检查一次状态
setInterval(checkServiceStatus, 30000);

// 导航栏滚动效果
window.addEventListener('scroll', function() {
    const navbar = document.getElementById('navbar');
    if (navbar) {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    }
});

// 复制代码功能
function copyCode(button) {
    const codeBlock = button.closest('.code-block');
    const code = codeBlock.querySelector('pre code');
    const text = code.textContent;
    
    navigator.clipboard.writeText(text).then(function() {
        // 显示复制成功提示
        const originalText = button.textContent;
        button.textContent = '✓ 已复制';
        button.style.background = 'var(--success)';
        button.style.color = 'white';
        button.style.borderColor = 'var(--success)';
        
        setTimeout(function() {
            button.textContent = originalText;
            button.style.background = '';
            button.style.color = '';
            button.style.borderColor = '';
        }, 2000);
    }).catch(function(err) {
        console.error('复制失败:', err);
        button.textContent = '复制失败';
        setTimeout(function() {
            button.textContent = '复制代码';
        }, 2000);
    });
}

// 平滑滚动到锚点
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href === '#') return;
        
        e.preventDefault();
        const target = document.querySelector(href);
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// 页面加载动画
window.addEventListener('load', function() {
    document.body.style.opacity = '0';
    setTimeout(function() {
        document.body.style.transition = 'opacity 0.3s ease';
        document.body.style.opacity = '1';
    }, 50);
});
