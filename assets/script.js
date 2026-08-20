'use strict';

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

let results = [];   
let busy = false;   


function go(name) {
    document.querySelectorAll('.page').forEach((p) => p.classList.remove('active'));
    $(`page-${name}`).classList.add('active');
}


let toastTimer;
function toast(msg, type = 'info') {
    const el = $('toast');
    el.textContent = msg;
    el.className = `toast show ${type}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = 'toast'), 2600);
}

const loading = (on, text = '正在检测，请稍候…') => {
    $('loading-text').textContent = text;
    $('loading').classList.toggle('hidden', !on);
};

/* ---------------- 配置 ---------------- */
async function loadConfig() {
    const res = await api().get_config_status();
    if (res.valid && res.config) {
        $('api-key').value = res.config.api_key || '';
        $('base-url').value = res.config.base_url || '';
        $('model').value = res.config.model || '';
        $('is-label').checked = !!res.config.is_label;
        return true;
    }
    return false;
}

async function saveConfig() {
    const apiKey = $('api-key').value.trim();
    const baseUrl = $('base-url').value.trim();
    const model = $('model').value.trim();
    if (!apiKey || !baseUrl || !model) return toast('API Key、Base URL 和 Model 均为必填项', 'error');

    loading(true, '正在校验配置…');
    try {
        const res = await api().save_config(apiKey, baseUrl, model, $('is-label').checked);
        toast(res.message, res.success ? 'success' : 'error');
        if (res.success) setTimeout(() => go('home'), 700);
    } catch (e) {
        console.error(e);
        toast('保存配置时发生错误', 'error');
    } finally {
        loading(false);
    }
}

/* ---------------- 检测 ---------------- */
async function detect() {
    if (busy) return;
    try {
        const picked = await api().select_images();
        if (!picked.success) return toast(picked.message || '文件选择失败', 'error');
        if (!picked.paths?.length) return toast('未选择任何图片', 'info');

        busy = true;
        loading(true, `正在检测 ${picked.paths.length} 张图片…`);
        const res = await api().start_generation(picked.paths, $('is-label').checked);
        if (!res.success) {
            busy = false;
            loading(false);
            toast(res.message || '任务启动失败', 'error');
        }
    } catch (e) {
        console.error(e);
        busy = false;
        loading(false);
        toast('检测过程发生错误', 'error');
    }
}

function render(data) {
    results = data || [];
    $('result-count').textContent = results.length ? `共 ${results.length} 张` : '';
    $('result-body').innerHTML = results.length
        ? results
            .map(
                (it) => `<tr>
                    <td><img class="thumb" src="${it.image}" alt="隐患图片"></td>
                    <td class="desc">${(it.label || '').trim() ? escapeHtml(it.label) : '<span class="ok">✅ 未发现隐患</span>'}</td>
                </tr>`
            )
            .join('')
        : '<tr><td colspan="2" class="empty">暂无检测结果</td></tr>';
    go('result');
}

const escapeHtml = (s) =>
    String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
        .replace(/\n/g, '<br>');

/* ---------------- 导出 ---------------- */
async function exportAs(kind) {
    if (!results.length) return toast('没有可导出的检测结果', 'error');
    loading(true, '正在导出…');
    try {
        const res = await (kind === 'excel' ? api().export_excel(results) : api().export_word(results));
        toast(res.success ? '导出成功，正在打开文件' : res.message, res.success ? 'success' : 'error');
    } catch (e) {
        console.error(e);
        toast('导出时发生错误', 'error');
    } finally {
        loading(false);
    }
}

/* ---------------- 后端回调 ---------------- */
window.taskStarted = () => loading(true);
window.taskCompleted = (success, message, data) => {
    busy = false;
    loading(false);
    if (!success) return toast(message, 'error');
    toast(message, 'success');
    render(data);
};

/* ---------------- 事件绑定 ---------------- */
const actions = { save: saveConfig, detect, 'export-excel': () => exportAs('excel'), 'export-word': () => exportAs('word') };

window.addEventListener('pywebviewready', async () => {
    document.addEventListener('click', (e) => {
        const el = e.target.closest('[data-go],[data-act]');
        if (!el) return;
        if (el.dataset.go) go(el.dataset.go);
        else actions[el.dataset.act]?.();
    });

    // 缩略图点击放大
    $('result-body').addEventListener('click', (e) => {
        if (!e.target.classList.contains('thumb')) return;
        $('viewer-img').src = e.target.src;
        $('viewer').classList.remove('hidden');
    });
    $('viewer').addEventListener('click', () => $('viewer').classList.add('hidden'));

    try {
        if (!(await loadConfig())) {
            go('config');
            toast('请先完成模型配置', 'info');
        }
    } catch (err) {
        console.error('[初始化失败]', err);
        go('config');
    }
});
