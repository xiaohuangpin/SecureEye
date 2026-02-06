window.addEventListener('pywebviewready', async function() {
    console.log('[PyWebView] API 已就绪，开始初始化应用');
    
    try {
        await initializeApp();
        document.getElementById('save-config').addEventListener('click', saveConfig);
        document.getElementById('btn-config').addEventListener('click', showConfigPage);
        document.getElementById('btn-generate').addEventListener('click', startGeneration);
    } catch (error) {
        console.error('[初始化错误]', error);
        showConfigPage();
        showError('应用初始化失败，请重试');
    }
});

// 全局状态
let currentPage = 'main'; // 'config' or 'main'

// 初始化应用
async function initializeApp() {
    try {
        console.log('[App] 调用 get_config_status...');
        const response = await pywebview.api.get_config_status();
        console.log('[App] 收到配置响应:', response);
        
        if (response.valid && response.config) {
            // 预填充配置（用于后续修改）
            document.getElementById('api-key').value = response.config.api_key || '';
            document.getElementById('base-url').value = response.config.base_url || '';
            document.getElementById('model').value = response.config.model || '';
            
            showMainPage();
        } else {
            console.log('[App] 配置无效，显示配置页面');
            showConfigPage();
        }
    } catch (error) {
        console.error('[初始化失败]', error);
        showConfigPage();
        // 不显示错误弹窗，避免首次启动时的干扰
    }
}

// 保存配置
async function saveConfig() {
    const apiKey = document.getElementById('api-key').value.trim();
    const baseUrl = document.getElementById('base-url').value.trim();
    const model = document.getElementById('model').value.trim();
    
    // 验证输入
    if (!apiKey || !baseUrl || !model) {
        showError('所有字段均为必填项');
        return;
    }

    try {
        const response = await pywebview.api.save_config(apiKey, baseUrl, model);
        
        if (response.success) {
            showSuccess(response.message);
            setTimeout(showMainPage, 1000);
        } else {
            showError(response.message || '保存配置失败');
        }
    } catch (error) {
        console.error('保存配置错误:', error);
        showError('保存配置时发生错误');
    }
}


async function startGeneration() {
    try {
        
        const fileResponse = await pywebview.api.select_images();
        
        if (!fileResponse.success) {
            showError(fileResponse.message || '文件选择失败');
            return;
        }
        
        if (!fileResponse.paths || fileResponse.paths.length === 0) {
            showInfo('未选择任何图片');
            return;
        }
        
        
        document.getElementById('progress-container').classList.remove('hidden');
        document.getElementById('status-message').classList.add('hidden');
        
       
        const genResponse = await pywebview.api.start_generation(fileResponse.paths);
        
        if (!genResponse.success) {
            hideProgress();
            showError(genResponse.message || '任务启动失败');
        }
    } catch (error) {
        console.error('生成报告错误:', error);
        hideProgress();
        showError('生成报告时发生错误');
    }
}


function showConfigPage() {
    document.getElementById('config-page').classList.add('active');
    document.getElementById('main-page').classList.remove('active');
    currentPage = 'config';
    hideProgress();
    clearStatus();
}


function showMainPage() {
    document.getElementById('main-page').classList.add('active');
    document.getElementById('config-page').classList.remove('active');
    currentPage = 'main';
    hideProgress();
    clearStatus();
}


function hideProgress() {
    document.getElementById('progress-container').classList.add('hidden');
}


function clearStatus() {
    const statusEl = document.getElementById('status-message');
    statusEl.classList.add('hidden');
    statusEl.innerHTML = '';
    statusEl.className = 'status hidden';
}


function showSuccess(message) {
    updateStatus(message, 'success');
}


function showError(message) {
    updateStatus(message, 'error');
}


function showInfo(message) {
    updateStatus(message, 'info');
}


function updateStatus(message, type) {
    const statusEl = document.getElementById('status-message');
    statusEl.textContent = message;
    statusEl.className = `status ${type}`;
    statusEl.classList.remove('hidden');
    
    
    if (type === 'success') {
        setTimeout(() => {
            if (statusEl.textContent === message) {
                statusEl.classList.add('hidden');
            }
        }, 3000);
    }
}


window.taskStarted = () => {
   
};

window.taskCompleted = (success, message) => {
    hideProgress();
    
    if (success) {
        showSuccess(message);
    } else {
        showError(message);
    }
};


window.onerror = function(msg, url, lineNo, columnNo, error) {
    console.error('全局错误:', {msg, url, lineNo, columnNo, error});
    if (currentPage === 'main') {
        showError('应用发生错误，请查看控制台');
    }
    return false;
};