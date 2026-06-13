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
  
  // Record initial coverage
  let initialCoverageValue = null;
  const recentCoverageEl = document.getElementById("recentCoverage");

  // Statistics related elements
  const llmGenerationCountEl = document.getElementById("llmGenerationCount");
  const compileSuccessRateEl = document.getElementById("compileSuccessRate");
  const emulatorSuccessCountEl = document.getElementById("emulatorSuccessCount");
  const emulatorSuccessRateEl = document.getElementById("emulatorSuccessRate");
  const coverageImprovedCountEl = document.getElementById("coverageImprovedCount");
  const coverageImprovedRateEl = document.getElementById("coverageImprovedRate");
  
  // Debugging: Check if element exists
  console.log('[统计] DOM元素检查:', {
    llmGenerationCountEl: !!llmGenerationCountEl,
    compileSuccessRateEl: !!compileSuccessRateEl,
    emulatorSuccessCountEl: !!emulatorSuccessCountEl,
    emulatorSuccessRateEl: !!emulatorSuccessRateEl,
    coverageImprovedCountEl: !!coverageImprovedCountEl,
    coverageImprovedRateEl: !!coverageImprovedRateEl
  });

  // Chart example
  let statisticsChart = null;
  let coverageChart = null;

  // Model configuration
  const paramModelTypeEl = document.getElementById("paramModelType");
  const paramModelEl = document.getElementById("paramModel");

  // Model option configuration
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

  // Update model options
  const updateModelOptions = (type) => {
    if (!paramModelEl) return;
    const options = modelOptions[type] || modelOptions.commercial;
    paramModelEl.innerHTML = options
      .map((opt) => `<option value="${opt.value}">${opt.label}</option>`)
      .join("");
  };

  // Monitor model type changes
  if (paramModelTypeEl) {
    paramModelTypeEl.addEventListener("change", (e) => {
      updateModelOptions(e.target.value);
    });
    // initialization
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
  const appendLog = (line) => {
    if (!logOutEl) return;
    logOutEl.textContent += (logOutEl.textContent ? "\n" : "") + line;
    logOutEl.scrollTop = logOutEl.scrollHeight;
    
    // Parse coverage data
    parseCoverageData(line);
  };

  // Status: Whether the coverage lines are being collected
  let collectingCoverageLines = false;
  let expectedCoverageCount = 0;
  let collectedCoverageCount = 0;

  const parseCoverageData = (line) => {
    // Match: "This test covers X lines of code" (supports various prefixes such as emoji)
    const coveredMatch = line.match(/本次测试覆盖了\s*(\d+)\s*行代码/);
    if (coveredMatch && coveredLinesEl) {
      const count = parseInt(coveredMatch[1], 10);
      coveredLinesEl.textContent = count;
      
      // Start collecting covered lines of code
      collectingCoverageLines = true;
      expectedCoverageCount = count;
      collectedCoverageCount = 0;
    }
    
    // Matches: "Newly covered lines of code (first X lines):" - from global coverage check
    const newCoveredMatch = line.match(/新覆盖的代码行\s*\(前\s*(\d+)\s*行\)/);
    if (newCoveredMatch) {
      const count = parseInt(newCoveredMatch[1], 10);
      // Start collecting covered lines of code
      collectingCoverageLines = true;
      expectedCoverageCount = count;
      collectedCoverageCount = 0;
    }

    // Match: "Current number of reference cases: X" or "Current number of reference cases: X" (supports Chinese and English colons)
    // The number of good_seeds in the backend is consistent, and the "Run module reference case" and "Number of successfully covered cases" are updated at the same time.
    const casesMatch = line.match(/当前参考案例数[：:]\s*(\d+)/);
    if (casesMatch) {
      const count = parseInt(casesMatch[1], 10);
      if (successCasesEl) successCasesEl.textContent = count;
      if (coverageImprovedCountEl) coverageImprovedCountEl.textContent = count;
      // If there are LLM generation times that can be calculated as a ratio, the interface will not be pulled repeatedly here, and the ratio will still be updated by statistical polling.
    }

    // Match covered lines of code only if in collection state
    // Format: " 1. %000000 xxx" or " 1. xxx" (actual code line)
    if (collectingCoverageLines && recentCoverageEl) {
      const lineMatch = line.match(/^\s*(\d+)\.\s+(.+)$/);
      if (lineMatch) {
        const lineNum = parseInt(lineMatch[1], 10);
        let codeLine = lineMatch[2].trim();
        
        // Process verilator format: "%000000 | code" -> extract the code part
        if (codeLine.startsWith('%')) {
          const pipeIndex = codeLine.indexOf('|');
          if (pipeIndex > 0) {
            codeLine = codeLine.substring(pipeIndex + 1).trim();
          }
        }
        
        // Display as long as there is content (simplifying the judgment logic)
        if (codeLine.length >= 3) {
          collectedCoverageCount++;
          
          // Removed "Waiting to overwrite data..." prompt
          const empty = recentCoverageEl.querySelector('.recent__empty');
          if (empty) empty.remove();
          
          // Add new coverage lines (keeps up to the most recent 30)
          const item = document.createElement('div');
          item.className = 'recent__item';
          item.textContent = codeLine;
          item.title = `第 ${lineNum} 行: ${codeLine}`;
          recentCoverageEl.insertBefore(item, recentCoverageEl.firstChild);
          
          // limited quantity
          const items = recentCoverageEl.querySelectorAll('.recent__item');
          if (items.length > 30) {
            items[items.length - 1].remove();
          }
          
          // Stop when you have collected enough
          if (collectedCoverageCount >= expectedCoverageCount) {
            collectingCoverageLines = false;
          }
        }
      }
      
      // Stop collection when encountering "... and X lines left"
      if (line.includes('还有') && line.includes('行')) {
        collectingCoverageLines = false;
      }
    }
  };
  const clearLog = () => {
    if (logOutEl) logOutEl.textContent = "";
    // Clear coverage data at the same time
    if (coveredLinesEl) coveredLinesEl.textContent = "0";
    if (successCasesEl) successCasesEl.textContent = "0";
    if (recentCoverageEl) {
      recentCoverageEl.innerHTML = '<div class="recent__empty">等待覆盖数据...</div>';
    }
    // Reset collection status
    collectingCoverageLines = false;
    expectedCoverageCount = 0;
    collectedCoverageCount = 0;
  };

  // Get overall coverage (read from server file)
  let coverageFailCount = 0;
  const fetchTotalCoverage = async () => {
    const { base, token, runId } = getConfig();
    if (!base || !runId) return;
    
    // If it fails 3 times in a row, polling is paused.
    if (coverageFailCount >= 3) {
      console.warn('总体覆盖率连续获取失败，已暂停轮询');
      stopCoveragePolling();
      return;
    }
    
    try {
      // Call the API to get overall coverage data
      const data = await fetchJson(`${base}/api/runs/${encodeURIComponent(runId)}/coverage`, token);
      
      // Reset failure count after success
      coverageFailCount = 0;
      
      // Handling no-data status (fresh mode or coverage data not yet generated)
      if (data.status === "no_data" || data.status === "fresh_mode" || data.status === "fresh_mode_waiting") {
        // If it is Fresh mode, reset the initial coverage value
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
        // Do not set initialCoverageValue and wait until the data is actually obtained before recording it.
        return;
      }
      
      // Handle error status
      if (data.status === "error" || data.status === "parse_error") {
        console.warn("覆盖率获取错误:", data.message || data.status);
        // If there is a parsing error but there is no historical data, an error message will be displayed.
        if (data.status === "parse_error" && !data.coverage_percentage) {
          if (totalCoverageEl) totalCoverageEl.textContent = "解析失败";
          if (coverageDeltaEl) {
            coverageDeltaEl.textContent = "-";
            coverageDeltaEl.style.color = "#888";
          }
        }
        return;
      }
      
      // Handle parsing errors but use cache
      if (data.status === "parse_error_using_cache") {
        console.warn("覆盖率解析失败，使用缓存数据:", data.warning);
        // Continue to update the display with cached data
      }
      
      if (data.coverage_percentage !== undefined) {
        const currentCoverage = data.coverage_percentage;
        
        // Record initial coverage (only recorded on first acquisition)
        if (initialCoverageValue === null) {
          initialCoverageValue = currentCoverage;
          if (initialCoverageEl) {
            initialCoverageEl.textContent = `${currentCoverage.toFixed(2)}%`;
          }
        }
        
        // Update current coverage
        if (totalCoverageEl) {
          totalCoverageEl.textContent = `${currentCoverage.toFixed(2)}%`;
        }
        
        // Calculate and display delta
        if (coverageDeltaEl && initialCoverageValue !== null) {
          const delta = currentCoverage - initialCoverageValue;
          if (delta > 0) {
            coverageDeltaEl.textContent = `+${delta.toFixed(3)}%`;
            coverageDeltaEl.style.color = "#4ade80"; // green
          } else if (delta < 0) {
            coverageDeltaEl.textContent = `${delta.toFixed(3)}%`;
            coverageDeltaEl.style.color = "#f87171"; // red
          } else {
            coverageDeltaEl.textContent = "+0%";
            coverageDeltaEl.style.color = "#888"; // grey
          }
        }
      }
      
      if (totalLinesEl && data.total_covered_lines !== undefined) {
        totalLinesEl.textContent = data.total_covered_lines.toLocaleString();
      }
    } catch (err) {
      // 408 timeout or other error
      coverageFailCount++;
      
      // Fails silently and does not affect other functions
      // 408 timeout is normal (genhtml may take a long time) and no error is displayed.
      if (!err.message?.includes('408')) {
        console.warn('获取总体覆盖率失败:', err);
      }
    }
  };

  // Get overall coverage periodically (every 2 minutes)
  let coverageTimer = null;
  const startCoveragePolling = () => {
    if (coverageTimer) clearInterval(coverageTimer);
    coverageFailCount = 0; // Reset failure count
    fetchTotalCoverage();
    coverageTimer = setInterval(fetchTotalCoverage, 120000);
  };
  const stopCoveragePolling = () => {
    if (coverageTimer) {
      clearInterval(coverageTimer);
      coverageTimer = null;
    }
  };

  // Initialize empty chart (display placeholder information)
  const initEmptyChart = (canvasId, chartType) => {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // If the chart already exists, do not create it again
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
          backgroundColor: isBar ? 'rgba(169, 182, 218, 0.2)' : 'rgba(231, 76, 60, 0.1)',
          borderColor: isBar ? 'rgba(169, 182, 218, 0.5)' : 'rgba(231, 76, 60, 0.5)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: isBar ? {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: 'rgba(169, 182, 218, 0.8)', font: { size: 10 } }
          },
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: 'rgba(169, 182, 218, 0.8)', font: { size: 10 } }
          }
        } : {
          y: {
            beginAtZero: false,
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: 'rgba(169, 182, 218, 0.8)', font: { size: 10 } }
          },
          x: {
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: 'rgba(169, 182, 218, 0.8)', font: { size: 10 } }
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              color: 'rgba(169, 182, 218, 0.9)',
              font: { size: 10 },
              padding: 8,
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

  // Get statistics
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
        
        // Update statistics
        if (llmGenerationCountEl) {
          const count = summary.total_llm_generations || 0;
          llmGenerationCountEl.textContent = count;
          console.log(`[统计] LLM生成次数: ${count}`);
        }
        if (compileSuccessRateEl) {
          const rate = summary.compile_success_rate || 0;
          if (rate > 0) {
            compileSuccessRateEl.textContent = `${rate.toFixed(2)}%`;
            compileSuccessRateEl.style.color = rate >= 80 ? "#4ade80" : rate >= 50 ? "#fbbf24" : "#f87171";
            console.log(`[统计] 编译成功率: ${rate.toFixed(2)}%`);
          } else {
            compileSuccessRateEl.textContent = "-";
            compileSuccessRateEl.style.color = "#888";
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
            emulatorSuccessRateEl.style.color = rate >= 80 ? "#4ade80" : rate >= 50 ? "#fbbf24" : "#f87171";
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
            coverageImprovedRateEl.style.color = rate >= 80 ? "#4ade80" : rate >= 50 ? "#fbbf24" : "#f87171";
            console.log(`[统计] 占 LLM 生成比例: ${(rate || 0).toFixed(2)}%`);
          } else {
            coverageImprovedRateEl.textContent = "-";
            coverageImprovedRateEl.style.color = "#888";
            console.log('[统计] 占 LLM 生成比例: 无数据');
          }
        }

        // Update statistical chart
        if (data.modules && data.modules.length > 0) {
          updateStatisticsChart(data.modules);
        } else {
          // If there is no module data, initialize an empty chart
          initEmptyChart("statisticsChart", "bar");
        }
        
        // Update coverage chart
        if (data.coverage_data && data.coverage_data.length > 0) {
          updateCoverageChart(data.coverage_data);
        } else {
          // If there is no coverage data, initialize an empty chart
          initEmptyChart("coverageChart", "line");
        }
      } else if (data.status === "no_data") {
        console.log('[统计] 暂无统计数据（当前任务尚未写入或未匹配），保留日志中的实时值');
        // Only indicators without "log real-time source" are updated, and do not cover "running module reference cases", "number of successfully covered cases", "proportion of LLM generation" (updated by the log "current number of reference cases", etc.)
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
        // Do not cover coverageImprovedCountEl / successCasesEl / coverageImprovedRateEl, retain the displayed values ​​​​such as the log "current number of reference cases"
        // Initialize empty chart
        if (!statisticsChart) initEmptyChart("statisticsChart", "bar");
        if (!coverageChart) initEmptyChart("coverageChart", "line");
      } else {
        console.log('[统计] 未知状态:', data.status);
      }
    } catch (err) {
      console.warn('[统计] 获取统计数据失败:', err);
      // Also initialize empty charts when errors occur to avoid blank spaces
      if (!statisticsChart) initEmptyChart("statisticsChart", "bar");
      if (!coverageChart) initEmptyChart("coverageChart", "line");
    }
  };

  // Update statistical chart
  const updateStatisticsChart = (modules) => {
    const ctx = document.getElementById("statisticsChart");
    if (!ctx) return;

    if (!modules || modules.length === 0) {
      // If there is no data, initialize an empty chart
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
              backgroundColor: 'rgba(74, 144, 226, 0.6)',
              borderColor: 'rgba(74, 144, 226, 1)',
              borderWidth: 1
            },
            {
              label: '模拟器成功执行次数',
              data: emulatorCounts,
              backgroundColor: 'rgba(80, 200, 120, 0.6)',
              borderColor: 'rgba(80, 200, 120, 1)',
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
              grid: {
                color: 'rgba(255, 255, 255, 0.05)'
              },
              ticks: {
                color: 'rgba(169, 182, 218, 0.8)',
                font: {
                  size: 10
                }
              }
            },
            x: {
              grid: {
                color: 'rgba(255, 255, 255, 0.05)'
              },
              ticks: {
                color: 'rgba(169, 182, 218, 0.8)',
                font: {
                  size: 10
                },
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
                color: 'rgba(169, 182, 218, 0.9)',
                font: {
                  size: 10
                },
                padding: 8,
                usePointStyle: true
              }
            }
          }
        }
      });
    }
  };

  // Update coverage chart
  const updateCoverageChart = (coverageData) => {
    const ctx = document.getElementById("coverageChart");
    if (!ctx) return;

    if (!coverageData || coverageData.length === 0) {
      // If there is no data, initialize an empty chart
      if (!coverageChart) {
        initEmptyChart("coverageChart", "line");
      }
      return;
    }

    // Sort by time
    const sortedData = [...coverageData].sort((a, b) => a.timestamp - b.timestamp);
    
    const timestamps = sortedData.map(d => {
      const date = new Date(d.timestamp * 1000);
      return date.toLocaleTimeString();
    });
    const coveragePercentages = sortedData.map(d => d.coverage_percentage || 0);

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
            borderColor: 'rgba(231, 76, 60, 1)',
            backgroundColor: 'rgba(231, 76, 60, 0.1)',
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
              grid: {
                color: 'rgba(255, 255, 255, 0.05)'
              },
              ticks: {
                color: 'rgba(169, 182, 218, 0.8)',
                font: {
                  size: 10
                }
              },
              title: {
                display: false
              }
            },
            x: {
              grid: {
                color: 'rgba(255, 255, 255, 0.05)'
              },
              ticks: {
                color: 'rgba(169, 182, 218, 0.8)',
                font: {
                  size: 10
                },
                maxRotation: 45,
                minRotation: 0
              },
              title: {
                display: false
              }
            }
          },
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: {
                color: 'rgba(169, 182, 218, 0.9)',
                font: {
                  size: 10
                },
                padding: 8,
                usePointStyle: true
              }
            }
          }
        }
      });
    }
  };

  // Obtain statistical data regularly (every 10 seconds to facilitate timely updating of "number of successfully covered cases" etc.)
  let statisticsTimer = null;
  const startStatisticsPolling = () => {
    if (statisticsTimer) clearInterval(statisticsTimer);
    console.log('[统计] 启动统计轮询');
    // Initialize empty charts immediately to avoid blank spaces
    initEmptyChart("statisticsChart", "bar");
    initEmptyChart("coverageChart", "line");
    // Get data immediately
    fetchStatistics();
    // Obtained every 10 seconds (original 30 seconds, shortened so that the number of successfully covered cases can be updated in time)
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

  // When "coverage is successful" appears in the verification process, the statistics are immediately refreshed so that the "number of successfully covered cases" is updated in a timely manner.
  window.addEventListener('chipfuzz-refresh-statistics', () => {
    if (typeof fetchStatistics === 'function') fetchStatistics();
  });

  // Get the total number of reference cases (statistics from GJ_Success_Seed directory)
  // Only obtained when the task is connected
  const fetchSuccessSeeds = async () => {
    const { base, token, runId } = getConfig();
    if (!base || !runId) return;  // Need to have runId to obtain
    
    try {
      const data = await fetchJson(`${base}/api/success-seeds`, token);
      
      if (totalSuccessSeedsEl && data.count !== undefined) {
        totalSuccessSeedsEl.textContent = data.count;
      }
    } catch (err) {
      // Silently fails
      console.warn('获取总参考案例数失败:', err);
    }
  };

  // Get the total number of reference cases periodically (every 30 seconds)
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
    // If base ends with /api, remove it (avoid double paths)
    // Supports multiple formats: /api, /api/, /api/xxx, etc.
    if (base.endsWith("/api")) {
      base = base.slice(0, -4);
    }
    // Make sure base does not end with /
    base = base.replace(/\/+$/, "");
    const token = (apiTokenEl?.value || "").trim();
    const runId = (runIdEl?.value || "").trim();
    return { base, token, runId };
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
    setConnState("未连接");
    setLogHint("等待连接…");
  };

  const authHeaders = (token) => (token ? { Authorization: `Bearer ${token}` } : {});

  const fetchJson = async (url, token) => {
    const res = await fetch(url, { headers: { ...authHeaders(token) } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  };

  const connectSSE = ({ base, token, runId }) => {
    // EventSource cannot customize headers; if authentication is required, it is recommended to use cookies of the same domain, or add tokens to the URL (not recommended).
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
    pollTimer = setInterval(tick, 1500);
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

    // Reset initial coverage (relog when new tasks are connected)
    initialCoverageValue = null;
    if (initialCoverageEl) initialCoverageEl.textContent = "获取中...";
    if (totalCoverageEl) totalCoverageEl.textContent = "获取中...";
    if (coverageDeltaEl) {
      coverageDeltaEl.textContent = "-";
      coverageDeltaEl.style.color = "#888";
    }
    // Reset this success story and overwrite the code line
    if (successCasesEl) successCasesEl.textContent = "0";
    if (recentCoverageEl) {
      recentCoverageEl.innerHTML = '<div class="recent__empty">等待覆盖数据...</div>';
    }

    // Start polling
    startCoveragePolling();
    startSuccessSeedsPolling();
    startStatisticsPolling();
    startL2Polling();

    // Use polling mode by default (more stable and versatile)
    setLogHint("使用轮询模式获取日志");
    connectPolling({ base, token, runId });
  };

  if (btnStartRun) {
    btnStartRun.addEventListener("click", async () => {
      const { base, token } = getConfig();
      if (!base) {
        setLogHint("请先填写 API Base");
        return;
      }
      
      // Get task parameters
      const params = {
        module: document.getElementById("paramModule")?.value || "Bku",
        model: document.getElementById("paramModel")?.value || "qwen3:235b",
        mode: document.getElementById("paramMode")?.value || "continue",
        max_iterations: parseInt(document.getElementById("paramMaxIterations")?.value) || 13,
        num: parseInt(document.getElementById("paramNum")?.value) || 100,
        auto_switch: document.getElementById("paramAutoSwitch")?.checked ?? true, // Default true (checkbox is checked by default)
        use_spec: document.getElementById("paramUseSpec")?.checked || false,
        run_existing_seeds: document.getElementById("paramRunExistingSeeds")?.checked || false,
        // Use the default path and no longer get it from the front end
        coverage_filename_origin: "/root/XiangShan/logs/annotated/",
        coverage_filename_later: "/root/XiangShan/logs2/annotated/",
        global_annotated_dir: "/root/XiangShan/logs_global/annotated",
      };
      
      // Confirm fresh mode
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
        
        // Reset initial coverage (re-record when new task starts)
        initialCoverageValue = null;
        if (initialCoverageEl) initialCoverageEl.textContent = "等待数据...";
        if (totalCoverageEl) totalCoverageEl.textContent = "等待数据...";
        if (coverageDeltaEl) {
          coverageDeltaEl.textContent = "-";
          coverageDeltaEl.style.color = "#888";
        }
        // Reset this success story
        if (successCasesEl) successCasesEl.textContent = "0";
        // Reset recently overridden lines of code
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

  // L2 module group coverage
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
      
      // Update summary data
      if (l2TotalCoverageEl && data.summary) {
        l2TotalCoverageEl.textContent = `${data.summary.coverage_rate}%`;
      }
      if (l2CoveredLinesEl && data.summary) {
        l2CoveredLinesEl.textContent = data.summary.covered_lines;
      }
      if (l2UncoveredLinesEl && data.summary) {
        l2UncoveredLinesEl.textContent = data.summary.uncovered_lines;
      }
      
      // Update module list
      if (l2ModulesListEl && data.modules) {
        l2ModulesListEl.innerHTML = "";
        
        for (const [name, stats] of Object.entries(data.modules)) {
          const item = document.createElement("div");
          item.className = "l2-module-item";
          item.style.cssText = "padding: 8px 12px; background: var(--card-bg); border-radius: 6px; border: 1px solid var(--border);";
          
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
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>${statusIcon} ${name}</span>
                <span style="color: ${statusColor}; font-weight: 600;">${rate}%</span>
              </div>
              <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                ${stats.covered_lines}/${stats.total_lines} 行
              </div>
            `;
          } else {
            item.innerHTML = `
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>⚪ ${name}</span>
                <span style="color: var(--text-muted);">N/A</span>
              </div>
              <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                文件不存在
              </div>
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

  // Periodically refresh L2 coverage (every 60 seconds)
  let l2Timer = null;
  const startL2Polling = () => {
    console.log("[L2] startL2Polling 被调用");
    if (l2Timer) clearInterval(l2Timer);
    fetchL2Coverage();
    l2Timer = setInterval(fetchL2Coverage, 60000);
  };

})();

