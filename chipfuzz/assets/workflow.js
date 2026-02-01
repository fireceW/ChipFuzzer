/**
 * 验证流程实时展示 —— 极简 3 区块版本
 *
 * 只展示 3 类关键信息：
 *  1. LLM 生成的用例（展示实际汇编代码，关键部分）
 *  2. 编译 & 仿真执行的命令 / 结果
 *  3. 覆盖率分析的结论（提升了多少、是否异常）
 *
 * 特性：
 *  - 任务开始时自动清空列表（只保留本次 flow）
 *  - 汇编代码只显示关键部分（前5行+后5行，中间用 ..... 代替）
 *  - 自动读取 .S 文件和 LLM 输出文件，提取实际代码
 */

(() => {
  'use strict';

  const MAX_ITEMS = 30;  // 每个列表最多保留30条
  const CODE_PREVIEW_LINES = 10;  // 代码预览：前10行 + 后10行（增加信息量）

  let genListEl = null;  // LLM 生成用例
  let cmdListEl = null;  // 编译 / 仿真命令 & 结果
  let covListEl = null;  // 覆盖率分析摘要
  let covSummaryBox = null;  // 四合一摘要框
  let covEmptyEl = null;
  let apiBase = null;  // API 基础路径
  /** 覆盖率摘要四项合并到一个框 */
  let latestCovSummary = { status: '', rate: '', lines: '', caseName: '' };
  /** 当前 case：编译命令、编译是否成功、仿真命令、仿真是否成功 合并为一块 */
  let currentCase = { compileCmd: '', compileOk: '', simCmd: '', simOk: '' };

  /** HTML 转义 */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /** 提取汇编代码的关键部分（前N行 + 后N行，中间用 ..... 代替） */
  function extractKeyCode(fullCode) {
    if (!fullCode) return '';
    const lines = fullCode.split('\n').filter(l => l.trim());
    if (lines.length <= CODE_PREVIEW_LINES * 2) {
      return fullCode;  // 代码太短，直接返回全部
    }
    const head = lines.slice(0, CODE_PREVIEW_LINES).join('\n');
    const tail = lines.slice(-CODE_PREVIEW_LINES).join('\n');
    return `${head}\n.....\n${tail}`;
  }

  /** 从 LLM 输出中提取 ```assembly 代码块 */
  function extractAssemblyFromLLMOutput(content) {
    // 匹配 ```assembly ... ``` 或 '''assembly ... '''
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

  /** 从输入框获取规范化的 API Base（去掉尾部 / 和 /api） */
  function ensureApiBase() {
    if (apiBase) return apiBase;
    const apiBaseEl = document.getElementById('apiBase');
    let raw = apiBaseEl ? (apiBaseEl.value || '') : '';
    if (!raw) raw = 'http://localhost'; // 与 main.js 保持一致
    raw = raw.trim();
    // 去掉尾部的 /
    while (raw.endsWith('/')) raw = raw.slice(0, -1);
    // 如果以 /api 结尾，去掉这一段，避免出现 /api/api/...
    if (raw.toLowerCase().endsWith('/api')) {
      raw = raw.slice(0, -4);
    }
    apiBase = raw;
    return apiBase;
  }

  /** 读取文件内容（调用后端 API） */
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

  /** 将 currentCase 渲染到「编译/仿真」区域的唯一一块中（实时刷新，不追加，避免 DOM 过多卡顿） */
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

  /** 完成当前 case 并清空，下次将刷新为新区块内容（不追加历史，仅保留一块） */
  function flushCaseBlock() {
    if (!cmdListEl) return;
    const c = currentCase;
    if (!c.compileCmd && !c.compileOk && !c.simCmd && !c.simOk) return;
    renderCurrentCaseBlock();
    currentCase = { compileCmd: '', compileOk: '', simCmd: '', simOk: '' };
  }

  /** 追加一条记录。appendAtEnd=true 时按时间顺序（先编译后仿真），否则最新在上方。
   * 注意：编译/仿真区域只允许通过 flushCaseBlock() 追加，不在此处单独追加。 */
  function appendItem(targetEl, title, content, isCode = false, appendAtEnd = false) {
    if (!targetEl) return;
    if (targetEl === cmdListEl) return;  // 编译/仿真只用一个框输出，不单独 append
    if (!content || !content.trim()) return;

    // 第一次插入时移除空提示
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
      // 超出时删掉最上面（最旧）的一条
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

  /** 提取路径中的用例文件名（如 Bku_asm_20260129_170905_594489d1.S） */
  function basename(path) {
    if (!path) return '';
    const parts = path.replace(/\\/g, '/').split('/');
    return parts[parts.length - 1] || path;
  }

  /** 处理汇编文件路径：读取文件并展示关键代码 + 用例文件名（实时更新，只保留最新一条） */
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

  /** 处理 LLM 输出文件路径：读取文件并提取代码块，标题带文件名 */
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

  /** 四合一：更新覆盖率摘要框（覆盖成功/无新覆盖、当前覆盖率、本次多覆盖、成功用例） */
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

  /** 处理单行日志，根据模式分派到 3 块 */
  function handleLogLine(line) {
    const text = (line || '').trim();
    if (!text) return;
    const lower = text.toLowerCase();

    // 粗暴一点：只要这一行里出现“汇编代码已保存到”，就先打 log
    if (text.includes('汇编代码已保存到')) {
      console.log('[Workflow] 收到包含“汇编代码已保存到”的日志行:', text);
    }

    // 检测任务开始，清空所有列表
    if (/== 任务已启动 ==|正在启动任务|开始运行|启动新任务/.test(text)) {
      resetFlow();
      return;
    }

    // 1) 检测到汇编文件保存路径，立即读取文件内容（实时更新）
    // 支持多种格式：✅ 汇编代码已保存到: xxx.S 或 汇编代码已保存到：xxx.S（中文冒号）
    if (text.includes('汇编代码已保存到') && text.includes('.S')) {
      // 尝试多种正则模式提取路径
      let filePath = null;
      const patterns = [
        /汇编代码已保存到[:：]\s*([^\s]+\.S)/i,
        /汇编代码已保存到[:：]\s*(.+\.S)/i,
        /([\/\w]+\.S)/i  // 最后的兜底：直接找路径格式
      ];
      
      for (const pattern of patterns) {
        const match = text.match(pattern);
        if (match && match[1]) {
          filePath = match[1].trim();
          // 确保是完整路径
          if (filePath.startsWith('/root/') || filePath.startsWith('./') || filePath.includes('testcase/') || filePath.includes('all_seed/')) {
            break;
          }
        }
      }
      
      if (filePath) {
        console.log('[Workflow] 🚀 实时检测到新汇编文件，立即读取:', filePath);
        // 立即读取并显示（实时更新）
        handleAssemblyFile(filePath);
        return;
      } else {
        console.warn('[Workflow] ⚠️ 检测到"汇编代码已保存到"但无法提取路径，原文:', text);
      }
    }

    // 2) 检测到 LLM 输出文件路径，读取并提取代码块
    const llmOutputMatch = text.match(/LLM 原始输出已写入:\s*(.+\.txt)/i);
    if (llmOutputMatch) {
      const filePath = llmOutputMatch[1].trim();
      handleLLMOutputFile(filePath);
      return;
    }

    // 3) LLM 生成用例相关（其他信息）
    if (
      /正在调用 llm|llm 响应时间/.test(text) ||
      /生成的 asm 文件/.test(text) ||
      /成功提取汇编代码/.test(text)
    ) {
      appendItem(genListEl, 'LLM 生成用例', text);
      return;
    }

    // 4) 编译命令 — 单块实时刷新，不追加
    if (/完整命令:\s*sh\s+complier\.sh/i.test(text) || /执行命令:?\s*sh\s+complier\.sh/i.test(text)) {
      const match = text.match(/(?:完整命令|执行命令):?\s*(sh\s+complier\.sh\s+\S+)/i) || text.match(/(sh\s+complier\.sh\s+\S+)/i);
      const cmd = match ? match[1].trim() : text;
      if (currentCase.compileCmd) flushCaseBlock();
      currentCase.compileCmd = cmd;
      renderCurrentCaseBlock();
      return;
    }
    // 5) 仿真命令
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

    // 验证流程：编译/仿真结果 — 实时刷新同一块
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
    // 无新覆盖时：解析用例名并显示「用例名 该case没有覆盖新的代码」
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

    // 6) 覆盖率分析摘要：四项合并到一个框
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
    // 以下不再显示：新统计行未覆盖、coverage.info 已更新、正在应用/更新覆盖率、合并文件等
  }

  /** 监听终端日志输出，做增量解析 */
  function setupLogListener() {
    const logOut = document.getElementById('logOut');
    if (!logOut) {
      console.error('[Workflow] #logOut 元素不存在！');
      return;
    }

    console.log('[Workflow] 开始监听 #logOut，当前内容长度:', logOut.textContent.length);

    let lastLen = 0;
    let lastContent = '';

    // 使用 setInterval 定期检查 textContent 变化（更可靠）
    const checkInterval = setInterval(() => {
      const currentContent = logOut.textContent || '';
      const currentLen = currentContent.length;

      if (currentLen > lastLen) {
        const delta = currentContent.slice(lastLen);
        lastLen = currentLen;
        lastContent = currentContent;

        // 按行处理新增内容
        const lines = delta.split('\n').filter(l => l.trim());
        if (lines.length > 0) {
          console.log('[Workflow] 检测到新增日志，行数:', lines.length);
          for (const line of lines) {
            handleLogLine(line);
          }
        }
      }
    }, 400); // 每 400ms 检查一次，降低长时间运行时的 CPU 占用

    // 同时保留 MutationObserver 作为备用
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

  /** 重置三个面板（任务开始时调用） */
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

  /** 从后端 API 获取最近生成的汇编代码（只保留最新一条） */
  let _recentAssemblyCodesNetworkErrorLogged = false;
  async function fetchRecentAssemblyCodes() {
    const base = ensureApiBase();
    if (!base) return;
    try {
      const url = `${base}/api/recent-assembly-codes?limit=1`;  // 只获取最新1条
      const response = await fetch(url);
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error(`[Workflow] API 请求失败 ${response.status}:`, errorText);
        return;
      }
      
      _recentAssemblyCodesNetworkErrorLogged = false; // 成功后重置，方便下次断线时再提示
      const data = await response.json();
      
      if (data.error) {
        console.warn('[Workflow] API 返回错误:', data.error);
      }
      
      if (data.codes && data.codes.length > 0) {
        genListEl.innerHTML = '';
        const latestCode = data.codes[0];
        const fileName = latestCode.name || '';
        appendItem(genListEl, fileName ? `LLM 生成用例 · ${fileName}` : 'LLM 生成用例', latestCode.key_code, true);
      }
    } catch (error) {
      if (error.name === 'TypeError' && (error.message === 'Failed to fetch' || error.message.includes('fetch'))) {
        if (!_recentAssemblyCodesNetworkErrorLogged) {
          _recentAssemblyCodesNetworkErrorLogged = true;
          console.warn('[Workflow] 无法连接服务端，请确认后端已启动且 API 地址正确（如 http://localhost:8080）');
        }
      } else {
        console.error('[Workflow] 获取最近汇编代码异常:', error);
      }
    }
  }

  /** 初始化入口 */
  function init() {
    console.log('[Workflow] init 开始');
    genListEl = document.getElementById('flowGenList');
    cmdListEl = document.getElementById('flowCmdList');
    covListEl = document.getElementById('flowCovList');
    covSummaryBox = document.getElementById('flowCovSummary');
    covEmptyEl = document.getElementById('flowCovEmpty');

    // 获取 API Base，并监听变化（与 main.js 行为保持一致）
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
    
    // 定期从后端获取最新生成的汇编代码（每 5 秒，作为兜底，确保不遗漏）
    // 主要依赖日志实时触发，这里只是补充
    // 注意：只保留最新一条，历史会自动清空
    setInterval(() => {
      if (genListEl) {
        fetchRecentAssemblyCodes();
      }
    }, 5000);
    
    // 立即获取一次（初始化时显示最新文件）
    setTimeout(() => fetchRecentAssemblyCodes(), 1000);

    // 监听任务开始按钮（额外保险）
    const btnStartRun = document.getElementById('btnStartRun');
    if (btnStartRun) {
      btnStartRun.addEventListener('click', () => {
        // 延迟一下，确保日志开始输出后再清空
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
