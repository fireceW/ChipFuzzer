(() => {
  const root = document.documentElement;

  // year
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  // theme
  const storageKey = "chipfuzzer-theme";
  const applyTheme = (theme) => {
    if (!theme) root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  };
  const saved = localStorage.getItem(storageKey);
  if (saved === "light" || saved === "dark") applyTheme(saved);

  const toggleBtn = document.getElementById("themeToggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      const cur = root.getAttribute("data-theme") || "dark";
      const next = cur === "dark" ? "light" : "dark";
      applyTheme(next);
      localStorage.setItem(storageKey, next);
    });
  }

  // copy buttons
  const copyButtons = document.querySelectorAll("[data-copy]");
  copyButtons.forEach((btn) => {
    btn.addEventListener("click", async () => {
      const sel = btn.getAttribute("data-copy");
      if (!sel) return;
      const el = document.querySelector(sel);
      if (!el) return;
      const text = el.textContent || "";
      try {
        await navigator.clipboard.writeText(text);
        const old = btn.textContent;
        btn.textContent = "已复制";
        setTimeout(() => (btn.textContent = old), 900);
      } catch {
        const old = btn.textContent;
        btn.textContent = "复制失败";
        setTimeout(() => (btn.textContent = old), 900);
      }
    });
  });

  // count-up animation
  const counters = document.querySelectorAll("[data-count]");
  const animate = (el) => {
    const target = Number(el.getAttribute("data-count") || "0");
    const start = 0;
    const duration = 800;
    const t0 = performance.now();
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      const val = Math.round(start + (target - start) * eased);
      el.textContent = String(val);
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const el = e.target;
        if (el.__done) continue;
        el.__done = true;
        animate(el);
      }
    },
    { threshold: 0.5 }
  );
  counters.forEach((c) => io.observe(c));

  // ---- monitor (SSE / fallback polling) ----
  const apiBaseEl = document.getElementById("apiBase");
  const apiTokenEl = document.getElementById("apiToken");
  const runIdEl = document.getElementById("runId");
  const btnStartRun = document.getElementById("btnStartRun");
  const btnConnect = document.getElementById("btnConnect");
  const btnDisconnect = document.getElementById("btnDisconnect");
  const btnListRuns = document.getElementById("btnListRuns");
  const btnStopRun = document.getElementById("btnStopRun");
  const btnClearLog = document.getElementById("btnClearLog");
  const connStateEl = document.getElementById("connState");
  const runStateEl = document.getElementById("runState");
  const logHintEl = document.getElementById("logHint");
  const logOutEl = document.getElementById("logOut");
  const initialCoverageEl = document.getElementById("initialCoverage");
  const totalCoverageEl = document.getElementById("totalCoverage");
  const coverageDeltaEl = document.getElementById("coverageDelta");
  const totalLinesEl = document.getElementById("totalLines");
  const totalSuccessSeedsEl = document.getElementById("totalSuccessSeeds");
  const coveredLinesEl = document.getElementById("coveredLines");
  const successCasesEl = document.getElementById("successCases");
  
  // 记录初始覆盖率
  let initialCoverageValue = null;
  const recentCoverageEl = document.getElementById("recentCoverage");

  // 统计相关元素
  const llmGenerationCountEl = document.getElementById("llmGenerationCount");
  const compileSuccessRateEl = document.getElementById("compileSuccessRate");
  const emulatorSuccessCountEl = document.getElementById("emulatorSuccessCount");
  const emulatorSuccessRateEl = document.getElementById("emulatorSuccessRate");
  const coverageImprovedCountEl = document.getElementById("coverageImprovedCount");
  const coverageImprovedRateEl = document.getElementById("coverageImprovedRate");
  
  // 调试：检查元素是否存在
  console.log('[统计] DOM元素检查:', {
    llmGenerationCountEl: !!llmGenerationCountEl,
    compileSuccessRateEl: !!compileSuccessRateEl,
    emulatorSuccessCountEl: !!emulatorSuccessCountEl,
    emulatorSuccessRateEl: !!emulatorSuccessRateEl,
    coverageImprovedCountEl: !!coverageImprovedCountEl,
    coverageImprovedRateEl: !!coverageImprovedRateEl
  });

  // 图表实例
  let statisticsChart = null;
  let coverageChart = null;

  // 模型配置
  const paramModelTypeEl = document.getElementById("paramModelType");
  const paramModelEl = document.getElementById("paramModel");

  // 模型选项配置
  const modelOptions = {
    commercial: [
      { value: "gpt-5.1", label: "gpt-5.1" },
      { value: "gpt-4o-2024-08-06", label: "gpt-4o-2024-08-06" },
      { value: "gpt-4-1106-preview", label: "gpt-4-1106-preview" },
      { value: "gpt-4-0314", label: "gpt-4-0314" },
    ],
    opensource: [
      { value: "qwen3:235b", label: "qwen3:235b" },
      { value: "deepseek-r1:671b", label: "deepseek-r1:671b" },
    ],
  };

  // 更新模型选项
  const updateModelOptions = (type) => {
    if (!paramModelEl) return;
    const options = modelOptions[type] || modelOptions.commercial;
    paramModelEl.innerHTML = options
      .map((opt) => `<option value="${opt.value}">${opt.label}</option>`)
      .join("");
  };

  // 监听模型类型变化
  if (paramModelTypeEl) {
    paramModelTypeEl.addEventListener("change", (e) => {
      updateModelOptions(e.target.value);
    });
    // 初始化
    updateModelOptions(paramModelTypeEl.value);
  }

  let es = null;
  let pollTimer = null;
  let logCursor = null;

  const setConnState = (t) => {
    if (connStateEl) connStateEl.textContent = t;
  };
  const setRunState = (t) => {
    if (runStateEl) runStateEl.textContent = t;
  };
  const setLogHint = (t) => {
    if (logHintEl) logHintEl.textContent = t;
  };
  // 限制实时日志行数，避免长时间运行后 DOM 过大导致卡死
  const LOG_MAX_LINES = 3000;
  const LOG_TRIM_TO = 2400;
  const appendLog = (line) => {
    if (!logOutEl) return;
    logOutEl.textContent += (logOutEl.textContent ? "\n" : "") + line;
    const lines = logOutEl.textContent.split("\n");
    if (lines.length > LOG_MAX_LINES) {
      logOutEl.textContent = lines.slice(-LOG_TRIM_TO).join("\n");
    }
    logOutEl.scrollTop = logOutEl.scrollHeight;
    // 解析覆盖率数据
    parseCoverageData(line);
  };

  // 状态：是否正在收集覆盖代码行
  let collectingCoverageLines = false;
  let expectedCoverageCount = 0;
  let collectedCoverageCount = 0;

  const parseCoverageData = (line) => {
    // 匹配: "本次测试覆盖了 X 行代码" (支持各种前缀如 emoji)
    const coveredMatch = line.match(/本次测试覆盖了\s*(\d+)\s*行代码/);
    if (coveredMatch && coveredLinesEl) {
      const count = parseInt(coveredMatch[1], 10);
      coveredLinesEl.textContent = count;
      
      // 开始收集覆盖的代码行
      collectingCoverageLines = true;
      expectedCoverageCount = count;
      collectedCoverageCount = 0;
    }
    
    // 匹配: "新覆盖的代码行 (前 X 行):" - 来自全局覆盖率检查
    const newCoveredMatch = line.match(/新覆盖的代码行\s*\(前\s*(\d+)\s*行\)/);
    if (newCoveredMatch) {
      const count = parseInt(newCoveredMatch[1], 10);
      // 开始收集覆盖的代码行
      collectingCoverageLines = true;
      expectedCoverageCount = count;
      collectedCoverageCount = 0;
    }

    // 匹配: "当前参考案例数: X" 或 "当前参考案例数：X"（支持中英文冒号）
    // 与后端 good_seeds 数量一致，同时更新「运行模块参考案例」和「成功覆盖 case 数」
    const casesMatch = line.match(/当前参考案例数[：:]\s*(\d+)/);
    if (casesMatch) {
      const count = parseInt(casesMatch[1], 10);
      if (successCasesEl) successCasesEl.textContent = count;
      if (coverageImprovedCountEl) coverageImprovedCountEl.textContent = count;
      // 若有 LLM 生成次数可算比例，此处不重复拉接口，比例仍由统计轮询更新
    }

    // 只有在收集状态下才匹配覆盖的代码行
    // 格式: "  1. %000000 xxx" 或 "   1. xxx"（实际代码行）
    if (collectingCoverageLines && recentCoverageEl) {
      const lineMatch = line.match(/^\s*(\d+)\.\s+(.+)$/);
      if (lineMatch) {
        const lineNum = parseInt(lineMatch[1], 10);
        let codeLine = lineMatch[2].trim();
        
        // 处理 verilator 格式: "%000000  | code" -> 提取 code 部分
        if (codeLine.startsWith('%')) {
          const pipeIndex = codeLine.indexOf('|');
          if (pipeIndex > 0) {
            codeLine = codeLine.substring(pipeIndex + 1).trim();
          }
        }
        
        // 只要有内容就显示（简化判断逻辑）
        if (codeLine.length >= 3) {
          collectedCoverageCount++;
          
          // 移除"等待覆盖数据..."提示
          const empty = recentCoverageEl.querySelector('.recent__empty');
          if (empty) empty.remove();
          
          // 添加新的覆盖行（最多保留最近 30 条）
          const item = document.createElement('div');
          item.className = 'recent__item';
          item.textContent = codeLine;
          item.title = `第 ${lineNum} 行: ${codeLine}`;
          recentCoverageEl.insertBefore(item, recentCoverageEl.firstChild);
          if (recentCoverageEl.children.length > 30) {
            recentCoverageEl.lastElementChild?.remove();
          }
          
          // 收集够了就停止
          if (collectedCoverageCount >= expectedCoverageCount) {
            collectingCoverageLines = false;
          }
        }
      }
      
      // 遇到 "... 还有 X 行" 时停止收集
      if (line.includes('还有') && line.includes('行')) {
        collectingCoverageLines = false;
      }
    }
  };
  const clearLog = () => {
    if (logOutEl) logOutEl.textContent = "";
    // 同时清空覆盖率数据
    if (coveredLinesEl) coveredLinesEl.textContent = "0";
    if (successCasesEl) successCasesEl.textContent = "0";
    if (recentCoverageEl) {
      recentCoverageEl.innerHTML = '<div class="recent__empty">等待覆盖数据...</div>';
    }
    // 重置收集状态
    collectingCoverageLines = false;
    expectedCoverageCount = 0;
    collectedCoverageCount = 0;
  };

  // 获取总体覆盖率（从服务器文件读取）
  let coverageFailCount = 0;
  const fetchTotalCoverage = async () => {
    const { base, token, runId } = getConfig();
    if (!base || !runId) return;
    
    // 如果连续失败 3 次，暂停轮询
    if (coverageFailCount >= 3) {
      console.warn('总体覆盖率连续获取失败，已暂停轮询');
      stopCoveragePolling();
      return;
    }
    
    try {
      // 调用 API 获取总体覆盖率数据
      const data = await fetchJson(`${base}/api/runs/${encodeURIComponent(runId)}/coverage`, token);
      
      // 成功后重置失败计数
      coverageFailCount = 0;
      
      // 处理无数据状态（fresh 模式或尚未生成覆盖率数据）
      if (data.status === "no_data" || data.status === "fresh_mode" || data.status === "fresh_mode_waiting") {
        // 如果是 Fresh 模式，重置初始覆盖率值
        if (data.status === "fresh_mode") {
          initialCoverageValue = null;
          console.log("🔄 Fresh 模式检测到，重置初始覆盖率值和基线");
        }
        if (initialCoverageEl) initialCoverageEl.textContent = "0.00%";
        if (totalCoverageEl) totalCoverageEl.textContent = "等待中...";
        if (coverageDeltaEl) {
          coverageDeltaEl.textContent = "-";
          coverageDeltaEl.style.color = "#888";
        }
        if (totalLinesEl) totalLinesEl.textContent = "-";
        // 不设置 initialCoverageValue，等真正获取到数据再记录
        return;
      }
      
      // 处理错误状态
      if (data.status === "error" || data.status === "parse_error") {
        console.warn("覆盖率获取错误:", data.message || data.status);
        // 如果是解析错误但没有历史数据，显示错误提示
        if (data.status === "parse_error" && !data.coverage_percentage) {
          if (totalCoverageEl) totalCoverageEl.textContent = "解析失败";
          if (coverageDeltaEl) {
            coverageDeltaEl.textContent = "-";
            coverageDeltaEl.style.color = "#888";
          }
        }
        return;
      }
      
      // 处理解析错误但使用缓存的情况
      if (data.status === "parse_error_using_cache") {
        console.warn("覆盖率解析失败，使用缓存数据:", data.warning);
        // 继续使用缓存的数据更新显示
      }
      
      if (data.coverage_percentage !== undefined) {
        const currentCoverage = data.coverage_percentage;
        
        // 记录初始覆盖率（只在第一次获取时记录）
        if (initialCoverageValue === null) {
          initialCoverageValue = currentCoverage;
          if (initialCoverageEl) {
            initialCoverageEl.textContent = `${currentCoverage.toFixed(2)}%`;
          }
        }
        
        // 更新当前覆盖率
        if (totalCoverageEl) {
          totalCoverageEl.textContent = `${currentCoverage.toFixed(2)}%`;
        }
        
        // 计算并显示增量
        if (coverageDeltaEl && initialCoverageValue !== null) {
          const delta = currentCoverage - initialCoverageValue;
          if (delta > 0) {
            coverageDeltaEl.textContent = `+${delta.toFixed(3)}%`;
            coverageDeltaEl.style.color = "var(--success, #34d399)"; // 绿色
          } else if (delta < 0) {
            coverageDeltaEl.textContent = `${delta.toFixed(3)}%`;
            coverageDeltaEl.style.color = "var(--danger, #f87171)"; // 红色
          } else {
            coverageDeltaEl.textContent = "+0%";
            coverageDeltaEl.style.color = "#888"; // 灰色
          }
        }
      }
      
      if (totalLinesEl && data.total_covered_lines !== undefined) {
        totalLinesEl.textContent = data.total_covered_lines.toLocaleString();
      }
    } catch (err) {
      // 408 超时或其他错误
      coverageFailCount++;
      
      // 静默失败，不影响其他功能
      // 408 超时是正常现象（genhtml 可能需要较长时间），不显示错误
      if (!err.message?.includes('408')) {
        console.warn('获取总体覆盖率失败:', err);
      }
    }
  };

  // 定期获取总体覆盖率（每 2 分钟）
  let coverageTimer = null;
  const startCoveragePolling = () => {
    if (coverageTimer) clearInterval(coverageTimer);
    coverageFailCount = 0; // 重置失败计数
    fetchTotalCoverage();
    coverageTimer = setInterval(fetchTotalCoverage, 120000);
  };
  const stopCoveragePolling = () => {
    if (coverageTimer) {
      clearInterval(coverageTimer);
      coverageTimer = null;
    }
  };

  // 初始化空图表（显示占位信息）
  const initEmptyChart = (canvasId, chartType) => {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // 如果图表已存在，不重复创建
    if (canvasId === "statisticsChart" && statisticsChart) return;
    if (canvasId === "coverageChart" && coverageChart) return;

    const isBar = chartType === "bar";
    const chart = new Chart(ctx, {
      type: chartType,
      data: {
        labels: isBar ? ["等待数据..."] : [],
        datasets: [{
          label: isBar ? "等待数据" : "覆盖率 (%)",
          data: isBar ? [0] : [],
          backgroundColor: isBar ? 'rgba(45, 212, 191, 0.35)' : 'rgba(45, 212, 191, 0.2)',
          borderColor: isBar ? 'rgba(45, 212, 191, 0.9)' : 'rgba(45, 212, 191, 0.9)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: isBar ? {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(0, 0, 0, 0.08)' },
            ticks: { color: '#475569', font: { size: 13, weight: '500' } }
          },
          x: {
            grid: { color: 'rgba(0, 0, 0, 0.08)' },
            ticks: { color: '#475569', font: { size: 13, weight: '500' } }
          }
        } : {
          y: {
            beginAtZero: false,
            grid: { color: 'rgba(0, 0, 0, 0.08)' },
            ticks: { color: '#475569', font: { size: 13, weight: '500' } }
          },
          x: {
            grid: { color: 'rgba(0, 0, 0, 0.08)' },
            ticks: { color: '#475569', font: { size: 13, weight: '500' } }
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              color: '#334155',
              font: { size: 13, weight: '600' },
              padding: 10,
              usePointStyle: true
            }
          }
        }
      }
    });

    if (canvasId === "statisticsChart") {
      statisticsChart = chart;
    } else if (canvasId === "coverageChart") {
      coverageChart = chart;
    }
  };

  // 获取统计数据
  const fetchStatistics = async () => {
    const { base, token, runId } = getConfig();
    if (!base || !runId) {
      console.log('[统计] 缺少 base 或 runId，跳过获取统计数据');
      return;
    }
    
    try {
      console.log(`[统计] 正在获取统计数据: ${base}/api/runs/${runId}/statistics`);
      const data = await fetchJson(`${base}/api/runs/${encodeURIComponent(runId)}/statistics`, token);
      console.log('[统计] 获取到的数据:', data);
      
      if (data.status === "success") {
        const summary = data.summary || {};
        
        console.log('[统计] 更新统计数据:', summary);
        
        // 更新统计数字
        if (llmGenerationCountEl) {
          const count = summary.total_llm_generations || 0;
          llmGenerationCountEl.textContent = count;
          console.log(`[统计] LLM生成次数: ${count}`);
        }
        if (compileSuccessRateEl) {
          const rate = summary.compile_success_rate || 0;
          if (rate > 0) {
            compileSuccessRateEl.textContent = `${rate.toFixed(2)}%`;
            compileSuccessRateEl.style.color = rate >= 80 ? "var(--success, #34d399)" : rate >= 50 ? "var(--warning, #fbbf24)" : "var(--danger, #f87171)";
            console.log(`[统计] 编译成功率: ${rate.toFixed(2)}%`);
          } else {
            compileSuccessRateEl.textContent = "-";
            compileSuccessRateEl.style.color = "var(--muted)";
            console.log('[统计] 编译成功率: 无数据');
          }
        }
        if (emulatorSuccessCountEl) {
          const count = summary.total_emulator_success || 0;
          emulatorSuccessCountEl.textContent = count;
          console.log(`[统计] 模拟器成功执行次数: ${count}`);
        }
        if (emulatorSuccessRateEl) {
          const rate = summary.emulator_success_rate || 0;
          if (rate > 0) {
            emulatorSuccessRateEl.textContent = `${rate.toFixed(2)}%`;
            emulatorSuccessRateEl.style.color = rate >= 80 ? "var(--success, #34d399)" : rate >= 50 ? "var(--warning, #fbbf24)" : "var(--danger, #f87171)";
            console.log(`[统计] 模拟器执行成功率: ${rate.toFixed(2)}%`);
          } else {
            emulatorSuccessRateEl.textContent = "-";
            emulatorSuccessRateEl.style.color = "#888";
            console.log('[统计] 模拟器执行成功率: 无数据');
          }
        }
        if (coverageImprovedCountEl) {
          const count = summary.total_coverage_improved ?? 0;
          coverageImprovedCountEl.textContent = count;
          console.log(`[统计] 成功覆盖 case 数: ${count}`);
        }
        if (coverageImprovedRateEl) {
          const rate = summary.coverage_improved_rate ?? 0;
          if (rate > 0 || (summary.total_llm_generations || 0) > 0) {
            coverageImprovedRateEl.textContent = `${(rate || 0).toFixed(2)}%`;
            coverageImprovedRateEl.style.color = rate >= 80 ? "var(--success, #34d399)" : rate >= 50 ? "var(--warning, #fbbf24)" : "var(--danger, #f87171)";
            console.log(`[统计] 占 LLM 生成比例: ${(rate || 0).toFixed(2)}%`);
          } else {
            coverageImprovedRateEl.textContent = "-";
            coverageImprovedRateEl.style.color = "#888";
            console.log('[统计] 占 LLM 生成比例: 无数据');
          }
        }

        // 更新统计图表
        if (data.modules && data.modules.length > 0) {
          updateStatisticsChart(data.modules);
        } else {
          // 如果没有模块数据，初始化空图表
          initEmptyChart("statisticsChart", "bar");
        }
        
        // 更新覆盖率图表
        if (data.coverage_data && data.coverage_data.length > 0) {
          updateCoverageChart(data.coverage_data);
        } else {
          // 如果没有覆盖率数据，初始化空图表
          initEmptyChart("coverageChart", "line");
        }
      } else if (data.status === "no_data") {
        console.log('[统计] 暂无统计数据（当前任务尚未写入或未匹配），保留日志中的实时值');
        // 仅更新无“日志实时来源”的指标，不覆盖「运行模块参考案例」「成功覆盖 case 数」「占 LLM 生成比例」（由日志「当前参考案例数」等更新）
        if (llmGenerationCountEl) llmGenerationCountEl.textContent = "0";
        if (compileSuccessRateEl) {
          compileSuccessRateEl.textContent = "-";
          compileSuccessRateEl.style.color = "#888";
        }
        if (emulatorSuccessCountEl) emulatorSuccessCountEl.textContent = "0";
        if (emulatorSuccessRateEl) {
          emulatorSuccessRateEl.textContent = "-";
          emulatorSuccessRateEl.style.color = "#888";
        }
        // 不覆盖 coverageImprovedCountEl / successCasesEl / coverageImprovedRateEl，保留日志「当前参考案例数」等已显示的值
        // 初始化空图表
        if (!statisticsChart) initEmptyChart("statisticsChart", "bar");
        if (!coverageChart) initEmptyChart("coverageChart", "line");
      } else {
        console.log('[统计] 未知状态:', data.status);
      }
    } catch (err) {
      console.warn('[统计] 获取统计数据失败:', err);
      // 出错时也初始化空图表，避免空白
      if (!statisticsChart) initEmptyChart("statisticsChart", "bar");
      if (!coverageChart) initEmptyChart("coverageChart", "line");
    }
  };

  // 更新统计图表
  const updateStatisticsChart = (modules) => {
    const ctx = document.getElementById("statisticsChart");
    if (!ctx) return;

    if (!modules || modules.length === 0) {
      // 如果没有数据，初始化空图表
      if (!statisticsChart) {
        initEmptyChart("statisticsChart", "bar");
      }
      return;
    }

    const moduleNames = modules.map(m => m.module_name || "unknown");
    const llmCounts = modules.map(m => m.llm_count || 0);
    const emulatorCounts = modules.map(m => m.emulator_success || 0);

    if (statisticsChart) {
      statisticsChart.data.labels = moduleNames;
      statisticsChart.data.datasets[0].data = llmCounts;
      if (statisticsChart.data.datasets.length > 1) {
        statisticsChart.data.datasets[1].data = emulatorCounts;
      }
      statisticsChart.update();
    } else {
      statisticsChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: moduleNames,
          datasets: [
            {
              label: 'LLM 生成次数',
              data: llmCounts,
              backgroundColor: 'rgba(45, 212, 191, 0.5)',
              borderColor: 'rgba(45, 212, 191, 0.95)',
              borderWidth: 1
            },
            {
              label: '模拟器成功执行次数',
              data: emulatorCounts,
              backgroundColor: 'rgba(94, 234, 212, 0.45)',
              borderColor: 'rgba(94, 234, 212, 0.9)',
              borderWidth: 1
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(0, 0, 0, 0.08)' },
              ticks: { color: '#475569', font: { size: 13, weight: '500' } }
            },
            x: {
              grid: { color: 'rgba(0, 0, 0, 0.08)' },
              ticks: {
                color: '#475569',
                font: { size: 13, weight: '500' },
                maxRotation: 45,
                minRotation: 0
              }
            }
          },
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: {
                color: '#334155',
                font: { size: 13, weight: '600' },
                padding: 10,
                usePointStyle: true
              }
            }
          }
        }
      });
    }
  };

  // 更新覆盖率图表
  const updateCoverageChart = (coverageData) => {
    const ctx = document.getElementById("coverageChart");
    if (!ctx) return;

    if (!coverageData || coverageData.length === 0) {
      // 如果没有数据，初始化空图表
      if (!coverageChart) {
        initEmptyChart("coverageChart", "line");
      }
      return;
    }

    // 按时间排序；若出现“先升后降”，把峰点当作异常值剔除
    const sortedData = [...coverageData].sort((a, b) => a.timestamp - b.timestamp);
    const toRemove = new Set();
    for (let i = 0; i < sortedData.length - 1; i++) {
      const pct = Number(sortedData[i].coverage_percentage) || 0;
      const nextPct = Number(sortedData[i + 1].coverage_percentage) || 0;
      if (pct > nextPct) toRemove.add(i); // 峰点（升后降的“升”）标为异常
    }
    const cleaned = sortedData.filter((_, i) => !toRemove.has(i));
    const timestamps = cleaned.map(d => {
      const date = new Date(d.timestamp * 1000);
      return date.toLocaleTimeString();
    });
    const coveragePercentages = cleaned.map(d => Number(d.coverage_percentage) || 0);

    if (coverageChart) {
      coverageChart.data.labels = timestamps;
      coverageChart.data.datasets[0].data = coveragePercentages;
      coverageChart.update();
    } else {
      coverageChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: timestamps,
          datasets: [{
            label: '覆盖率 (%)',
            data: coveragePercentages,
            borderColor: 'rgba(45, 212, 191, 0.95)',
            backgroundColor: 'rgba(45, 212, 191, 0.18)',
            borderWidth: 2,
            fill: true,
            tension: 0.4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: false,
              grid: { color: 'rgba(0, 0, 0, 0.08)' },
              ticks: { color: '#475569', font: { size: 13, weight: '500' } },
              title: { display: false }
            },
            x: {
              grid: { color: 'rgba(0, 0, 0, 0.08)' },
              ticks: {
                color: '#475569',
                font: { size: 13, weight: '500' },
                maxRotation: 45,
                minRotation: 0
              },
              title: { display: false }
            }
          },
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: {
                color: '#334155',
                font: { size: 13, weight: '600' },
                padding: 10,
                usePointStyle: true
              }
            }
          }
        }
      });
    }
  };

  // 定期获取统计数据（每 10 秒，便于“成功覆盖 case 数”等及时更新）
  let statisticsTimer = null;
  const startStatisticsPolling = () => {
    if (statisticsTimer) clearInterval(statisticsTimer);
    console.log('[统计] 启动统计轮询');
    // 立即初始化空图表，避免空白
    initEmptyChart("statisticsChart", "bar");
    initEmptyChart("coverageChart", "line");
    // 立即获取一次数据
    fetchStatistics();
    // 每10秒获取一次（原30秒，缩短以便成功覆盖 case 数及时更新）
    statisticsTimer = setInterval(() => {
      console.log('[统计] 定时获取统计数据...');
      fetchStatistics();
    }, 10000);
  };

  const stopStatisticsPolling = () => {
    if (statisticsTimer) {
      clearInterval(statisticsTimer);
      statisticsTimer = null;
    }
  };

  // 验证流程里出现「覆盖成功」时立即刷新统计，使「成功覆盖 case 数」及时更新
  window.addEventListener('chipfuzz-refresh-statistics', () => {
    if (typeof fetchStatistics === 'function') fetchStatistics();
  });

  // 获取总参考案例数（从 GJ_Success_Seed 目录统计）
  // 只有在已连接任务时才获取
  const fetchSuccessSeeds = async () => {
    const { base, token, runId } = getConfig();
    if (!base || !runId) return;  // 需要有 runId 才获取
    
    try {
      const data = await fetchJson(`${base}/api/success-seeds`, token);
      
      if (totalSuccessSeedsEl && data.count !== undefined) {
        totalSuccessSeedsEl.textContent = data.count;
      }
    } catch (err) {
      // 静默失败
      console.warn('获取总参考案例数失败:', err);
    }
  };

  // 定期获取总参考案例数（每 30 秒）
  let successSeedsTimer = null;
  const startSuccessSeedsPolling = () => {
    if (successSeedsTimer) clearInterval(successSeedsTimer);
    fetchSuccessSeeds();
    successSeedsTimer = setInterval(fetchSuccessSeeds, 30000);
  };
  const stopSuccessSeedsPolling = () => {
    if (successSeedsTimer) {
      clearInterval(successSeedsTimer);
      successSeedsTimer = null;
    }
  };

  const getConfig = () => {
    let base = (apiBaseEl?.value || "").trim().replace(/\/+$/, "");
    // 如果 base 以 /api 结尾，移除它（避免双重路径）
    // 支持多种格式：/api、/api/、/api/xxx 等
    if (base.endsWith("/api")) {
      base = base.slice(0, -4);
    }
    // 确保 base 不以 / 结尾
    base = base.replace(/\/+$/, "");
    const token = (apiTokenEl?.value || "").trim();
    const runId = (runIdEl?.value || "").trim();
    return { base, token, runId };
  };

  const stopL2Polling = () => {
    if (l2Timer) {
      clearInterval(l2Timer);
      l2Timer = null;
    }
  };

  const disconnect = () => {
    if (es) {
      es.close();
      es = null;
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    stopCoveragePolling();
    stopSuccessSeedsPolling();
    stopStatisticsPolling();
    stopL2Polling();
    setConnState("未连接");
    setLogHint("等待连接…");
  };

  const authHeaders = (token) => (token ? { Authorization: `Bearer ${token}` } : {});

  const FETCH_TIMEOUT_MS = 30000;
  const fetchJson = async (url, token) => {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(url, { headers: { ...authHeaders(token) }, signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (e.name === "AbortError") throw new Error("请求超时");
      throw e;
    } finally {
      clearTimeout(tid);
    }
  };

  const connectSSE = ({ base, token, runId }) => {
    // EventSource 无法自定义 header；若需要鉴权，建议用 cookie 同域，或在 URL 带 token（不推荐）。
    const url = `${base}/api/runs/${encodeURIComponent(runId)}/stream`;
    setConnState("SSE 连接中…");
    setLogHint("正在连接 SSE…");
    es = new EventSource(url, { withCredentials: true });

    es.addEventListener("open", () => {
      setConnState("已连接（SSE）");
      setLogHint("实时接收中…");
    });

    es.addEventListener("log", (e) => {
      appendLog(String(e.data || ""));
    });
    es.addEventListener("status", (e) => {
      try {
        const data = JSON.parse(e.data || "{}");
        if (data.state) setRunState(String(data.state));
      } catch {
        // ignore
      }
    });

    es.addEventListener("error", () => {
      setConnState("SSE 断开（将尝试轮询）");
      setLogHint("SSE 连接失败/断开，退化为轮询（若跨域/CORS 未配置也会导致失败）");
      es?.close();
      es = null;
      connectPolling({ base, token, runId });
    });
  };

  const connectPolling = ({ base, token, runId }) => {
    if (pollTimer) clearInterval(pollTimer);
    setConnState("轮询中…");
    const tick = async () => {
      try {
        // status
        const st = await fetchJson(`${base}/api/runs/${encodeURIComponent(runId)}/status`, token);
        if (st?.state) setRunState(String(st.state));

        // logs (incremental)
        const qs = logCursor ? `?cursor=${encodeURIComponent(logCursor)}` : "";
        const lg = await fetchJson(`${base}/api/runs/${encodeURIComponent(runId)}/logs${qs}`, token);
        if (Array.isArray(lg?.lines)) lg.lines.forEach((l) => appendLog(String(l)));
        if (lg?.nextCursor) logCursor = String(lg.nextCursor);
        setLogHint("轮询接收中…");
      } catch (err) {
        setLogHint(`轮询失败：${String(err?.message || err)}`);
      }
    };
    tick();
    pollTimer = setInterval(tick, 2000); // 2s 轮询，减轻服务与前端压力
  };

  const connect = async () => {
    disconnect();
    logCursor = null;
    const { base, token, runId } = getConfig();
    if (!base || !runId) {
      setLogHint("请先填写 API Base 和 Run ID");
      return;
    }
    
    setRunState("-");
    appendLog(`== 连接到 ${base}，runId=${runId} ==`);

    // 重置初始覆盖率（连接新任务时重新记录）
    initialCoverageValue = null;
    if (initialCoverageEl) initialCoverageEl.textContent = "获取中...";
    if (totalCoverageEl) totalCoverageEl.textContent = "获取中...";
    if (coverageDeltaEl) {
      coverageDeltaEl.textContent = "-";
      coverageDeltaEl.style.color = "#888";
    }
    // 重置本次成功案例和覆盖代码行
    if (successCasesEl) successCasesEl.textContent = "0";
    if (recentCoverageEl) {
      recentCoverageEl.innerHTML = '<div class="recent__empty">等待覆盖数据...</div>';
    }

    // 启动轮询
    startCoveragePolling();
    startSuccessSeedsPolling();
    startStatisticsPolling();
    startL2Polling();

    // 默认使用轮询模式（更稳定、更通用）
    setLogHint("使用轮询模式获取日志");
    connectPolling({ base, token, runId });
  };

  const paramModuleEl = document.getElementById("paramModule");
  const paramStartModuleIndexEl = document.getElementById("paramStartModuleIndex");

  if (btnStartRun) {
    btnStartRun.addEventListener("click", async () => {
      const { base, token } = getConfig();
      if (!base) {
        setLogHint("请先填写 API Base");
        return;
      }
      
      // 获取任务参数
      const startIdx = parseInt(paramStartModuleIndexEl?.value, 10);
      const params = {
        module: (paramModuleEl?.value || "").trim() || "LogPerfEndpoint",
        start_module_index: (Number.isNaN(startIdx) || startIdx < 1) ? null : startIdx,
        model: document.getElementById("paramModel")?.value || "qwen3:235b",
        mode: document.getElementById("paramMode")?.value || "continue",
        max_iterations: parseInt(document.getElementById("paramMaxIterations")?.value) || 13,
        num: parseInt(document.getElementById("paramNum")?.value) || 100,
        auto_switch: document.getElementById("paramAutoSwitch")?.checked ?? true,
        use_spec: document.getElementById("paramUseSpec")?.checked || false,
        run_existing_seeds: document.getElementById("paramRunExistingSeeds")?.checked || false,
        llm_report: document.getElementById("paramLlmReport")?.checked || false,
        coverage_filename_origin: "/root/XiangShan/logs/annotated/",
        coverage_filename_later: "/root/XiangShan/logs2/annotated/",
        global_annotated_dir: "/root/XiangShan/logs_global/annotated",
      };
      
      // 确认 fresh 模式
      if (params.mode === "fresh") {
        const confirmed = confirm("Fresh 模式会重置覆盖率文件（旧文件会备份），确定继续吗？");
        if (!confirmed) return;
      }
      
      try {
        setLogHint("正在启动任务...");
        const res = await fetch(`${base}/api/runs/start`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders(token),
          },
          body: JSON.stringify(params),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        appendLog(`== 任务已启动 ==\nrunId: ${data.runId}\npid: ${data.pid}\nmode: ${params.mode}\ncmd: ${JSON.stringify(data.cmd)}`);
        if (runIdEl) runIdEl.value = data.runId;
        setLogHint('任务已启动，可点击"连接日志流"查看实时输出');
        
        // 重置初始覆盖率（新任务开始时重新记录）
        initialCoverageValue = null;
        if (initialCoverageEl) initialCoverageEl.textContent = "等待数据...";
        if (totalCoverageEl) totalCoverageEl.textContent = "等待数据...";
        if (coverageDeltaEl) {
          coverageDeltaEl.textContent = "-";
          coverageDeltaEl.style.color = "#888";
        }
        // 重置本次成功案例
        if (successCasesEl) successCasesEl.textContent = "0";
        // 重置最近覆盖的代码行
        if (recentCoverageEl) {
          recentCoverageEl.innerHTML = '<div class="recent__empty">等待覆盖数据...</div>';
        }
      } catch (err) {
        setLogHint(`启动任务失败：${String(err?.message || err)}`);
        appendLog(`启动失败：${String(err)}`);
      }
    });
  }

  if (btnStopRun) {
    btnStopRun.addEventListener("click", async () => {
      const { base, token, runId } = getConfig();
      if (!base || !runId) {
        setLogHint("请先填写 Run ID");
        return;
      }
      
      const confirmed = confirm(`确定要停止任务 ${runId} 吗？`);
      if (!confirmed) return;
      
      try {
        setLogHint("正在停止任务...");
        const res = await fetch(`${base}/api/runs/${encodeURIComponent(runId)}/stop`, {
          method: "POST",
          headers: {
            ...authHeaders(token),
          },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        if (data.alreadyStopped) {
          appendLog(`== 任务已停止 ==\nrunId: ${runId}\n（任务已经停止）`);
          setLogHint("任务已经停止");
        } else {
          appendLog(`== 任务已停止 ==\nrunId: ${runId}\n已发送停止信号`);
          setLogHint("任务已停止");
          setRunState("stopped");
        }
      } catch (err) {
        setLogHint(`停止任务失败：${String(err?.message || err)}`);
        appendLog(`停止失败：${String(err)}`);
      }
    });
  }

  if (btnConnect) btnConnect.addEventListener("click", connect);
  if (btnDisconnect) btnDisconnect.addEventListener("click", disconnect);
  if (btnClearLog) btnClearLog.addEventListener("click", clearLog);
  if (btnListRuns) {
    btnListRuns.addEventListener("click", async () => {
      const { base, token } = getConfig();
      if (!base) {
        setLogHint("请先填写 API Base");
        return;
      }
      try {
        const data = await fetchJson(`${base}/api/runs`, token);
        appendLog(`== runs ==\n${JSON.stringify(data, null, 2)}`);
      } catch (err) {
        setLogHint(`获取任务列表失败：${String(err?.message || err)}`);
      }
    });
  }

  // L2 模块组覆盖率
  const l2TotalCoverageEl = document.getElementById("l2TotalCoverage");
  const l2CoveredLinesEl = document.getElementById("l2CoveredLines");
  const l2UncoveredLinesEl = document.getElementById("l2UncoveredLines");
  const l2ModulesListEl = document.getElementById("l2ModulesList");
  const btnRefreshL2 = document.getElementById("btnRefreshL2");

  const fetchL2Coverage = async () => {
    const { base, token } = getConfig();
    console.log("[L2] 开始获取 L2 覆盖率, base:", base);
    if (!base) {
      console.warn("[L2] base 为空，跳过");
      return;
    }
    
    try {
      console.log("[L2] 请求:", `${base}/api/l2-coverage`);
      const data = await fetchJson(`${base}/api/l2-coverage`, token);
      console.log("[L2] 响应数据:", data);
      
      // 更新汇总数据
      if (l2TotalCoverageEl && data.summary) {
        l2TotalCoverageEl.textContent = `${data.summary.coverage_rate}%`;
      }
      if (l2CoveredLinesEl && data.summary) {
        l2CoveredLinesEl.textContent = data.summary.covered_lines;
      }
      if (l2UncoveredLinesEl && data.summary) {
        l2UncoveredLinesEl.textContent = data.summary.uncovered_lines;
      }
      
      // 更新模块列表
      if (l2ModulesListEl && data.modules) {
        l2ModulesListEl.innerHTML = "";

        for (const [name, stats] of Object.entries(data.modules)) {
          const item = document.createElement("div");
          item.className = "l2-module-item";

          if (stats.exists) {
            const rate = stats.coverage_rate;
            let statusIcon = "🔴";
            let statusColor = "#ef4444";
            if (rate >= 90) {
              statusIcon = "🟢";
              statusColor = "#22c55e";
            } else if (rate >= 70) {
              statusIcon = "🟡";
              statusColor = "#eab308";
            }
            item.innerHTML = `
              <div class="l2-module-item__row">
                <span class="l2-module-item__name" title="${name}">${statusIcon} ${name}</span>
                <span class="l2-module-item__rate" style="color: ${statusColor}">${rate}%</span>
              </div>
              <div class="l2-module-item__lines">${stats.covered_lines}/${stats.total_lines} 行</div>
            `;
          } else {
            item.innerHTML = `
              <div class="l2-module-item__row">
                <span class="l2-module-item__name" title="${name}">⚪ ${name}</span>
                <span class="l2-module-item__rate" style="color: var(--muted)">N/A</span>
              </div>
              <div class="l2-module-item__lines">文件不存在</div>
            `;
          }
          l2ModulesListEl.appendChild(item);
        }
      }
    } catch (err) {
      console.warn("获取 L2 覆盖率失败:", err);
      if (l2ModulesListEl) {
        l2ModulesListEl.innerHTML = `<div class="recent__empty">获取失败: ${err.message}</div>`;
      }
    }
  };

  if (btnRefreshL2) {
    btnRefreshL2.addEventListener("click", () => {
      console.log("[L2] 刷新按钮被点击");
      fetchL2Coverage();
    });
  } else {
    console.warn("[L2] btnRefreshL2 元素不存在！");
  }

  // 定期刷新 L2 覆盖率（每 60 秒）
  let l2Timer = null;
  const startL2Polling = () => {
    console.log("[L2] startL2Polling 被调用");
    if (l2Timer) clearInterval(l2Timer);
    fetchL2Coverage();
    l2Timer = setInterval(fetchL2Coverage, 60000);
  };

})();

