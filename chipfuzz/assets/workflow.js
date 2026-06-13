/**
 * Runtime workflow documentation.
 *
 * Runtime workflow documentation.
 * Runtime workflow documentation.
 * Runtime workflow documentation.
 * Runtime workflow documentation.
 *
 * Runtime workflow documentation.
 * Runtime workflow documentation.
 * Runtime workflow documentation.
 * Runtime workflow documentation.
 */

(() => {
  'use strict';

  const MAX_ITEMS = 30;  // Each list can keep up to 30 items
  const CODE_PREVIEW_LINES = 10;  // Code preview: first 10 lines + last 10 lines (increases the amount of information)

  let genListEl = null;  // LLM generates use cases
  let cmdListEl = null;  // Compile/simulate commands & results
  let covListEl = null;  // Coverage analysis summary
  let covSummaryBox = null;  // 4-in-1 summary box
  let covEmptyEl = null;
  let apiBase = null;  // API base path
  /* Runtime workflow documentation.
  let latestCovSummary = { status: '', rate: '', lines: '', caseName: '' };
  /* Runtime workflow documentation.
  let currentCase = { compileCmd: '', compileOk: '', simCmd: '', simOk: '' };

  /* Runtime workflow documentation.
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* Runtime workflow documentation.
  function extractKeyCode(fullCode) {
    if (!fullCode) return '';
    const lines = fullCode.split('\n').filter(l => l.trim());
    if (lines.length <= CODE_PREVIEW_LINES * 2) {
      return fullCode;  // The code is too short, return all directly
    }
    const head = lines.slice(0, CODE_PREVIEW_LINES).join('\n');
    const tail = lines.slice(-CODE_PREVIEW_LINES).join('\n');
    return `${head}\n.....\n${tail}`;
  }

  /* Runtime workflow documentation.
  function extractAssemblyFromLLMOutput(content) {
    // UI/runtime helper.
    const patterns = [
      /```assembly\s*\n([\s\S]*?)\n```/,
      /'''assembly\s*\n([\s\S]*?)\n'''/,
    ];
    
    for (const pattern of patterns) {
      const match = content.match(pattern);
      if (match && match[1]) {
        return match[1].trim();
      }
    }
    return null;
  }

  /* Runtime workflow documentation.
  function ensureApiBase() {
    if (apiBase) return apiBase;
    const apiBaseEl = document.getElementById('apiBase');
    let raw = apiBaseEl ? (apiBaseEl.value || '') : '';
    if (!raw) raw = 'http:// localhost'; // consistent with main.js
    raw = raw.trim();
    // UI/runtime helper.
    while (raw.endsWith('/')) raw = raw.slice(0, -1);
    // UI/runtime helper.
    if (raw.toLowerCase().endsWith('/api')) {
      raw = raw.slice(0, -4);
    }
    apiBase = raw;
    return apiBase;
  }

  /* Runtime workflow documentation.
  async function readFileContent(filePath) {
    const base = ensureApiBase();

    try {
      const url = `${base}/api/files/read?path=${encodeURIComponent(filePath)}`;
      console.log('[Workflow] 请求文件:', url);
      const response = await fetch(url);
      if (!response.ok) {
        const errorText = await response.text();
        console.error(`[Workflow] HTTP ${response.status}:`, errorText);
        throw new Error(`HTTP ${response.status}: ${errorText}`);
      }
      const data = await response.json();
      if (!data.content) {
        console.warn('[Workflow] 返回数据中没有 content 字段:', data);
        return null;
      }
      return data.content;
    } catch (error) {
      console.error(`[Workflow] 读取文件失败 ${filePath}:`, error);
      return null;
    }
  }

  /* Runtime workflow documentation.
  function renderCurrentCaseBlock() {
    if (!cmdListEl) return;
    const c = currentCase;
    const empty = cmdListEl.querySelector('.workflow-output-empty');
    if (empty) empty.remove();

    let block = cmdListEl.querySelector('.workflow-case-block');
    if (!block) {
      block = document.createElement('div');
      block.className = 'workflow-output-item workflow-case-block';
      cmdListEl.appendChild(block);
    }
    const now = new Date().toLocaleTimeString();
    const compileOkText = c.compileOk || '—';
    const simCmdText = c.simCmd || '—';
    const simOkText = c.simOk || '—';
    const compileOkClass = c.compileOk === '编译成功' ? 'workflow-case-ok' : (c.compileOk === '编译失败' ? 'workflow-case-fail' : '');
    const simOkClass = c.simOk === '仿真成功' ? 'workflow-case-ok' : (c.simOk === '仿真失败' ? 'workflow-case-fail' : '');
    block.innerHTML = `
      <div class="workflow-output-timestamp">${now} · 当前 case（实时刷新）</div>
      <div class="workflow-case-rows">
        <div class="workflow-case-row"><span class="workflow-case-label">编译命令</span><span class="workflow-case-value">${escapeHtml(c.compileCmd || '—')}</span></div>
        <div class="workflow-case-row"><span class="workflow-case-label">编译是否成功</span><span class="workflow-case-value ${compileOkClass}">${escapeHtml(compileOkText)}</span></div>
        <div class="workflow-case-row"><span class="workflow-case-label">仿真命令</span><span class="workflow-case-value">${escapeHtml(simCmdText)}</span></div>
        <div class="workflow-case-row"><span class="workflow-case-label">仿真是否成功</span><span class="workflow-case-value ${simOkClass}">${escapeHtml(simOkText)}</span></div>
      </div>
    `;
  }

  /* Runtime workflow documentation.
  function flushCaseBlock() {
    if (!cmdListEl) return;
    const c = currentCase;
    if (!c.compileCmd && !c.compileOk && !c.simCmd && !c.simOk) return;
    renderCurrentCaseBlock();
    currentCase = { compileCmd: '', compileOk: '', simCmd: '', simOk: '' };
  }

  /* Runtime workflow documentation.
   * Runtime workflow documentation.
  function appendItem(targetEl, title, content, isCode = false, appendAtEnd = false) {
    if (!targetEl) return;
    if (targetEl === cmdListEl) return;  // Compilation/simulation only uses one box for output, no separate append
    if (!content || !content.trim()) return;

    // UI/runtime helper.
    const empty = targetEl.querySelector('.workflow-output-empty');
    if (empty) empty.remove();

    const now = new Date().toLocaleTimeString();
    const wrapper = document.createElement('div');
    wrapper.className = 'workflow-output-item';

    if (isCode) {
      const codeContent = escapeHtml(content);
      wrapper.innerHTML = `
        <div class="workflow-output-timestamp">${now} · ${escapeHtml(title)}</div>
        <pre class="workflow-code-preview">${codeContent}</pre>
      `;
    } else {
      const safe = escapeHtml(content).slice(0, 260);
      wrapper.innerHTML = `
        <div class="workflow-output-timestamp">${now} · ${escapeHtml(title)}</div>
        <div class="workflow-output-text">${safe}</div>
      `;
    }

    if (appendAtEnd) {
      targetEl.appendChild(wrapper);
      // UI/runtime helper.
      const items = targetEl.querySelectorAll('.workflow-output-item');
      if (items.length > MAX_ITEMS) {
        targetEl.removeChild(items[0]);
      }
    } else {
      targetEl.insertBefore(wrapper, targetEl.firstChild);
      const items = targetEl.querySelectorAll('.workflow-output-item');
      if (items.length > MAX_ITEMS) {
        targetEl.removeChild(targetEl.lastChild);
      }
    }
  }

  /* Runtime workflow documentation.
  function basename(path) {
    if (!path) return '';
    const parts = path.replace(/\\/g, '/').split('/');
    return parts[parts.length - 1] || path;
  }

  /* Runtime workflow documentation.
  async function handleAssemblyFile(filePath) {
    console.log('[Workflow] 🚀 实时读取新汇编文件:', filePath);
    const fileName = basename(filePath);
    
    const content = await readFileContent(filePath);
    if (!content) {
      console.error('[Workflow] ❌ 读取文件失败:', filePath);
      genListEl.innerHTML = '';
      appendItem(genListEl, `LLM 生成用例 · ${fileName}`, `❌ 读取失败: ${filePath}`);
      return;
    }
    
    console.log('[Workflow] ✅ 文件读取成功，长度:', content.length, '字符');
    const keyCode = extractKeyCode(content);
    
    genListEl.innerHTML = '';
    appendItem(genListEl, `LLM 生成用例 · ${fileName}`, keyCode, true);
    console.log('[Workflow] ✅ 实时更新完成，已清空历史，只显示最新代码');
  }

  /* Runtime workflow documentation.
  async function handleLLMOutputFile(filePath) {
    const fileName = basename(filePath);
    const content = await readFileContent(filePath);
    if (!content) {
      appendItem(genListEl, fileName ? `LLM 生成用例 · ${fileName}` : 'LLM 生成用例', `LLM 原始输出已写入: ${filePath}`);
      return;
    }
    
    const assemblyCode = extractAssemblyFromLLMOutput(content);
    if (assemblyCode) {
      const keyCode = extractKeyCode(assemblyCode);
      appendItem(genListEl, fileName ? `LLM 生成用例 · ${fileName}` : 'LLM 生成用例', keyCode, true);
    } else {
      appendItem(genListEl, fileName ? `LLM 生成用例 · ${fileName}` : 'LLM 生成用例', `LLM 原始输出已写入: ${filePath}`);
    }
  }

  /* Runtime workflow documentation.
  function updateCovSummaryBox() {
    if (!covSummaryBox || !covEmptyEl) return;
    const s = latestCovSummary;
    if (!s.status && !s.rate && !s.lines && !s.caseName) return;
    covEmptyEl.style.display = 'none';
    covSummaryBox.style.display = 'block';
    const parts = [];
    if (s.status) parts.push(`<div class="workflow-cov-summary-row"><span class="workflow-cov-summary-label">状态</span> ${escapeHtml(s.status)}</div>`);
    if (s.rate) parts.push(`<div class="workflow-cov-summary-row"><span class="workflow-cov-summary-label">当前覆盖率</span> ${escapeHtml(s.rate)}</div>`);
    if (s.lines) parts.push(`<div class="workflow-cov-summary-row"><span class="workflow-cov-summary-label">本次多覆盖</span> ${escapeHtml(s.lines)}</div>`);
    const caseLabel = (s.status === '无新覆盖' || s.status === '没有覆盖成功') ? '用例' : '成功用例';
    if (s.caseName) parts.push(`<div class="workflow-cov-summary-row"><span class="workflow-cov-summary-label">${escapeHtml(caseLabel)}</span> ${escapeHtml(s.caseName)}</div>`);
    covSummaryBox.innerHTML = parts.join('');
  }

  /* Runtime workflow documentation.
  function handleLogLine(line) {
    const text = (line || '').trim();
    if (!text) return;
    const lower = text.toLowerCase();

    // UI/runtime helper.
    if (text.includes('汇编代码已保存到')) {
      console.log('[Workflow] 收到包含“汇编代码已保存到”的日志行:', text);
    }

    // UI/runtime helper.
    if (/== 任务已启动 ==|正在启动任务|开始运行|启动新任务/.test(text)) {
      resetFlow();
      return;
    }

    // UI/runtime helper.
    // UI/runtime helper.
    if (text.includes('汇编代码已保存到') && text.includes('.S')) {
      // UI/runtime helper.
      let filePath = null;
      const patterns = [
        /汇编代码已保存到[:：]\s*([^\s]+\.S)/i,
        /汇编代码已保存到[:：]\s*(.+\.S)/i,
        /([\/\w]+\.S)/i  // The final tip: find the path format directly
      ];
      
      for (const pattern of patterns) {
        const match = text.match(pattern);
        if (match && match[1]) {
          filePath = match[1].trim();
          // UI/runtime helper.
          if (filePath.startsWith('/root/') || filePath.startsWith('./') || filePath.includes('testcase/') || filePath.includes('all_seed/')) {
            break;
          }
        }
      }
      
      if (filePath) {
        console.log('[Workflow] 🚀 实时检测到新汇编文件，立即读取:', filePath);
        // UI/runtime helper.
        handleAssemblyFile(filePath);
        return;
      } else {
        console.warn('[Workflow] ⚠️ 检测到"汇编代码已保存到"但无法提取路径，原文:', text);
      }
    }

    // UI/runtime helper.
    const llmOutputMatch = text.match(/LLM 原始输出已写入:\s*(.+\.txt)/i);
    if (llmOutputMatch) {
      const filePath = llmOutputMatch[1].trim();
      handleLLMOutputFile(filePath);
      return;
    }

    // UI/runtime helper.
    if (
      /正在调用 llm|llm 响应时间/.test(text) ||
      /生成的 asm 文件/.test(text) ||
      /成功提取汇编代码/.test(text)
    ) {
      appendItem(genListEl, 'LLM 生成用例', text);
      return;
    }

    // UI/runtime helper.
    if (/完整命令:\s*sh\s+complier\.sh/i.test(text) || /执行命令:?\s*sh\s+complier\.sh/i.test(text)) {
      const match = text.match(/(?:完整命令|执行命令):?\s*(sh\s+complier\.sh\s+\S+)/i) || text.match(/(sh\s+complier\.sh\s+\S+)/i);
      const cmd = match ? match[1].trim() : text;
      if (currentCase.compileCmd) flushCaseBlock();
      currentCase.compileCmd = cmd;
      renderCurrentCaseBlock();
      return;
    }
    // UI/runtime helper.
    if (/完整命令:.*(\.\/build\/emu|emu\s)/i.test(text)) {
      const match = text.match(/完整命令:\s*(.+)/);
      if (match) currentCase.simCmd = match[1].trim();
      renderCurrentCaseBlock();
      return;
    }
    if (/启动香山模拟器|启动模拟器/.test(text)) {
      currentCase.simCmd = text;
      renderCurrentCaseBlock();
      return;
    }

    // UI/runtime helper.
    if (/验证流程:\s*编译成功/.test(text)) {
      currentCase.compileOk = '编译成功';
      renderCurrentCaseBlock();
      return;
    }
    if (/验证流程:\s*编译失败/.test(text)) {
      currentCase.compileOk = '编译失败';
      flushCaseBlock();
      return;
    }
    if (/验证流程:\s*仿真成功/.test(text)) {
      currentCase.simOk = '仿真成功';
      flushCaseBlock();
      return;
    }
    if (/验证流程:\s*仿真失败/.test(text)) {
      currentCase.simOk = '仿真失败';
      flushCaseBlock();
      return;
    }
    if (/验证流程:\s*无新覆盖/.test(text)) {
      latestCovSummary.status = '无新覆盖';
      updateCovSummaryBox();
      return;
    }
    if (/验证流程:\s*没有覆盖成功/.test(text)) {
      latestCovSummary.status = '没有覆盖成功';
      updateCovSummaryBox();
      return;
    }
    // UI/runtime helper.
    const noCovCaseMatch = text.match(/验证流程:\s*无覆盖用例:\s*(.+)/);
    if (noCovCaseMatch) {
      latestCovSummary.caseName = noCovCaseMatch[1].trim() + ' 该case没有覆盖新的代码';
      updateCovSummaryBox();
      return;
    }
    if (/验证流程:\s*覆盖成功/.test(text)) {
      latestCovSummary.status = '覆盖成功';
      updateCovSummaryBox();
      try { window.dispatchEvent(new CustomEvent('chipfuzz-refresh-statistics')); } catch (_) {}
      return;
    }

    // UI/runtime helper.
    if (/L2 模块组|L2Cache|L2TLB|L2Directory|L2Top/i.test(text)) {
      return;
    }
    if (/当前覆盖率:\s*[\d.]+%/.test(text)) {
      latestCovSummary.rate = text.replace(/当前覆盖率:\s*/i, '').trim();
      updateCovSummaryBox();
      return;
    }
    if (/本次多覆盖:\s*\d+\s*行代码/.test(text)) {
      latestCovSummary.lines = text.replace(/本次多覆盖:?\s*/i, '').trim();
      updateCovSummaryBox();
      return;
    }
    if (/测试用例:.*多覆盖\s*\d+\s*行代码/.test(text)) {
      latestCovSummary.caseName = text.trim();
      updateCovSummaryBox();
      return;
    }
    if (/当前模块覆盖了\s*\d+\s*行代码/.test(text)) return;
    if (/警告：新未覆盖行数/.test(text)) return;
    // UI/runtime helper.
  }

  /* Runtime workflow documentation.
  function setupLogListener() {
    const logOut = document.getElementById('logOut');
    if (!logOut) {
      console.error('[Workflow] #logOut 元素不存在！');
      return;
    }

    console.log('[Workflow] 开始监听 #logOut，当前内容长度:', logOut.textContent.length);

    let lastLen = 0;
    let lastContent = '';

    // UI/runtime helper.
    const checkInterval = setInterval(() => {
      const currentContent = logOut.textContent || '';
      const currentLen = currentContent.length;

      if (currentLen > lastLen) {
        const delta = currentContent.slice(lastLen);
        lastLen = currentLen;
        lastContent = currentContent;

        // UI/runtime helper.
        const lines = delta.split('\n').filter(l => l.trim());
        if (lines.length > 0) {
          console.log('[Workflow] 检测到新增日志，行数:', lines.length);
          for (const line of lines) {
            handleLogLine(line);
          }
        }
      }
    }, 200); // Check every 200ms

    // UI/runtime helper.
    const observer = new MutationObserver(() => {
      const currentContent = logOut.textContent || '';
      const currentLen = currentContent.length;
      if (currentLen > lastLen) {
        const delta = currentContent.slice(lastLen);
        lastLen = currentLen;
        const lines = delta.split('\n').filter(l => l.trim());
        for (const line of lines) {
          handleLogLine(line);
        }
      }
    });

    observer.observe(logOut, { 
      childList: true, 
      subtree: true, 
      characterData: true,
      attributes: false
    });

    console.log('[Workflow] 已同时启用 setInterval 和 MutationObserver 监听');
  }

  /* Runtime workflow documentation.
  function resetFlow() {
    latestCovSummary = { status: '', rate: '', lines: '', caseName: '' };
    currentCase = { compileCmd: '', compileOk: '', simCmd: '', simOk: '' };
    if (genListEl) genListEl.innerHTML = '<div class="workflow-output-empty">等待任务开始...</div>';
    if (cmdListEl) cmdListEl.innerHTML = '<div class="workflow-output-empty">等待任务开始...</div>';
    if (covListEl) {
      covListEl.innerHTML = '<div id="flowCovSummary" class="workflow-cov-summary-box" style="display: none;"></div><div class="workflow-output-empty" id="flowCovEmpty">等待任务开始...</div>';
      covSummaryBox = document.getElementById('flowCovSummary');
      covEmptyEl = document.getElementById('flowCovEmpty');
    }
  }

  /* Runtime workflow documentation.
  async function fetchRecentAssemblyCodes() {
    const base = ensureApiBase();
    try {
      const url = `${base}/api/recent-assembly-codes?limit=1`;  // Get only the latest one
      console.log('[Workflow] 请求最近汇编代码:', url);
      const response = await fetch(url);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error(`[Workflow] API 请求失败 ${response.status}:`, errorText);
        return;
      }
      
      const data = await response.json();
      console.log('[Workflow] API 返回数据:', data);
      
      if (data.error) {
        console.warn('[Workflow] API 返回错误:', data.error);
      }
      
      if (data.codes && data.codes.length > 0) {
        genListEl.innerHTML = '';
        const latestCode = data.codes[0];
        const fileName = latestCode.name || '';
        console.log('[Workflow] 显示最新代码:', fileName);
        appendItem(genListEl, fileName ? `LLM 生成用例 · ${fileName}` : 'LLM 生成用例', latestCode.key_code, true);
      } else {
        console.log('[Workflow] 暂无汇编代码');
      }
    } catch (error) {
      console.error('[Workflow] 获取最近汇编代码异常:', error);
    }
  }

  /* Runtime workflow documentation.
  function init() {
    console.log('[Workflow] init 开始');
    genListEl = document.getElementById('flowGenList');
    cmdListEl = document.getElementById('flowCmdList');
    covListEl = document.getElementById('flowCovList');
    covSummaryBox = document.getElementById('flowCovSummary');
    covEmptyEl = document.getElementById('flowCovEmpty');

    // UI/runtime helper.
    const apiBaseEl = document.getElementById('apiBase');
    if (apiBaseEl) {
      ensureApiBase();
      apiBaseEl.addEventListener('change', () => {
        apiBase = null;
        ensureApiBase();
      });
    }

    resetFlow();
    setupLogListener();
    
    // UI/runtime helper.
    // UI/runtime helper.
    // UI/runtime helper.
    setInterval(() => {
      if (genListEl) {
        fetchRecentAssemblyCodes();
      }
    }, 5000);
    
    // UI/runtime helper.
    setTimeout(() => fetchRecentAssemblyCodes(), 1000);

    // UI/runtime helper.
    const btnStartRun = document.getElementById('btnStartRun');
    if (btnStartRun) {
      btnStartRun.addEventListener('click', () => {
        // UI/runtime helper.
        setTimeout(() => {
          resetFlow();
        }, 500);
      });
    }

    const resetBtn = document.getElementById('btnResetFlow');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        resetFlow();
      });
    }

    const exportBtn = document.getElementById('btnExportFlow');
    if (exportBtn) {
      exportBtn.addEventListener('click', () => {
        alert('建议使用浏览器的截图 / 捕获页面功能来保存该区域的图片。');
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
