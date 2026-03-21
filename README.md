# ChipFuzzer

一个基于大语言模型（LLM）的自动化硬件验证框架，专门为 XiangShan RISC-V 处理器设计，通过智能生成测试用例来提升代码覆盖率。

## 📋 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
- [Web UI 使用](#web-ui-使用)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

## 🎯 项目简介

ChipFuzzer 是一个创新的硬件验证框架，它结合了：
- **大语言模型（LLM）**：智能生成 RISC-V 汇编测试用例
- **代码覆盖率分析**：实时追踪和提升代码覆盖率
- **自动化测试流程**：从生成到编译、执行、分析的完整自动化
- **Web 可视化界面**：实时监控测试进度和覆盖率统计

该框架旨在解决传统硬件验证中测试用例生成效率低、覆盖率提升困难的问题，通过 LLM 的智能分析能力，自动生成针对性的测试用例。

## ✨ 核心特性

### 1. 智能测试用例生成
- **LLM 驱动**：支持多种 LLM 模型（OpenAI API、本地模型等）
- **上下文感知**：基于未覆盖代码和 SPEC 文件生成针对性测试用例
- **自动修复**：编译失败时自动调用 LLM 修复代码
- **策略多样化**：支持边界测试、CSR 测试、内存测试等多种策略

### 2. 代码覆盖率管理
- **全局覆盖率追踪**：实时统计和更新代码覆盖率
- **模块级分析**：支持按模块进行覆盖率测试和分析
- **增量覆盖**：只保留真正提升覆盖率的测试用例
- **L2 模块组统计**：专门针对 L2Cache、L2TLB 等关键模块的覆盖率统计

### 3. Agent 记忆系统
- **历史记录**：记录每次 LLM 交互的成功/失败经验
- **上下文复用**：利用历史成功案例指导新测试用例生成
- **策略学习**：从失败中学习，避免重复错误

### 4. SPEC 文件集成
- **自动解析**：解析 XiangShan SPEC 文件（`*spec*.sv`）
- **信号提取**：提取模块接口、信号宽度等关键信息
- **智能匹配**：将 SPEC 信息整合到 LLM prompt 中
- **测试建议**：基于 SPEC 生成针对性的测试策略

### 5. Web 可视化界面
- **实时监控**：SSE/轮询方式实时显示测试日志
- **覆盖率可视化**：图表展示覆盖率增长趋势
- **统计信息**：LLM 生成次数、编译成功率、模拟器执行成功率等
- **成功案例管理**：查看和管理成功提升覆盖率的测试用例

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      ChipFuzzer 框架                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  LLM 模块    │───▶│  代码生成    │───▶│  编译验证    │  │
│  │ (OpenAI/本地)│    │  (RISC-V ASM)│    │  (GCC/工具链)│  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    │          │
│         │                    ▼                    ▼          │
│         │            ┌──────────────┐    ┌──────────────┐  │
│         └───────────▶│  Agent Memory │    │  模拟器执行  │  │
│                      │  (历史记录)   │    │  (Emulator)  │  │
│                      └──────────────┘    └──────────────┘  │
│                                 │                    │      │
│                                 ▼                    ▼      │
│                      ┌──────────────────────────────┐      │
│                      │   覆盖率分析与管理            │      │
│                      │  (GlobalCoverageManager)     │      │
│                      └──────────────────────────────┘      │
│                                 │                           │
│                                 ▼                           │
│                      ┌──────────────────────────────┐      │
│                      │      Web UI (FastAPI)         │      │
│                      │   (实时监控/可视化)            │      │
│                      └──────────────────────────────┘      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 环境要求

- Python 3.8+
- RISC-V 工具链（GCC、objdump 等）
- Verilator（用于覆盖率分析）
- XiangShan 项目环境
- LLM API 访问权限（OpenAI API 或本地模型）

### 安装步骤

1. **克隆仓库**
```bash
git clone https://github.com/fireceW/ChipFuzzer.git
cd ChipFuzzer
```

2. **安装 Python 依赖**
```bash
pip install -r chipfuzz/server/requirements.txt
```

3. **配置路径**
编辑 `config.py` 或通过命令行参数设置：
- XiangShan 项目路径
- 覆盖率文件路径
- LLM API 配置

4. **启动 Web 服务（可选）**
```bash
cd chipfuzz/server
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

## 📖 使用指南

### 基本用法

```bash
# 测试单个模块
python xiangshan_fuzzing.py \
    --module Bku \
    --model qwen3:235b \
    --mode continue \
    --max_iterations 20

# 自动模式（测试多个模块）
python xiangshan_fuzzing.py \
    --module auto \
    --num 5 \
    --model qwen3:235b \
    --mode fresh \
    --auto_switch

# 使用 SPEC 文件增强
python xiangshan_fuzzing.py \
    --module L2TLB \
    --model qwen3:235b \
    --use_spec \
    --max_iterations 30
```

### 主要参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--module` | 要测试的模块名，或 `auto` 自动选择 | 必需 |
| `--model` | LLM 模型名称 | 必需 |
| `--mode` | 运行模式：`continue`（继续）或 `fresh`（重置） | `continue` |
| `--max_iterations` | 每个模块最大尝试次数 | `20` |
| `--num` | 自动模式下测试的模块数量 | `1` |
| `--auto_switch` | 自动切换模块（达到条件后） | `False` |
| `--use_spec` | 启用 SPEC 文件分析 | `False` |
| `--run_existing_seeds` | 运行已有成功用例 | `False` |

### 运行模式

#### Continue 模式
- 继续使用已有的覆盖率文件（`sum_gj.dat`）
- 在现有基础上提升覆盖率
- 适合持续测试和增量改进

#### Fresh 模式
- 创建全新的覆盖率基线
- 清空之前的覆盖率数据
- 适合重新开始或基准测试

## 🌐 Web UI 使用

### 启动服务

1. **启动后端 API**
```bash
cd chipfuzz/server
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

2. **配置 Nginx（可选，用于生产环境）**
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080/api/;
    proxy_http_version 1.1;
    proxy_buffering off;
}
```

3. **打开 Web 界面**
- 直接打开 `chipfuzz/index.html`
- 或通过 Web 服务器访问

### Web UI 功能

1. **连接配置**
   - API Base: `http://localhost` 或你的服务器地址
   - Run ID: 从启动任务后获取

2. **实时监控**
   - 实时日志流（SSE/轮询）
   - 任务状态显示
   - 覆盖率实时更新

3. **统计信息**
   - LLM 生成次数
   - 编译成功率
   - 模拟器执行成功率
   - 覆盖率增长曲线图

4. **成功案例**
   - 查看成功提升覆盖率的测试用例
   - 下载 `.S`、`.bin` 和报告文件

## ⚙️ 配置说明

### 路径配置

主要路径在 `config.py` 中定义：

```python
project_root = "/root/XiangShan/"
testcase_dir = "/root/XiangShan/testcase"
global_annotated_dir = "/root/XiangShan/logs_global/annotated"
sum_dat_file = "/root/XiangShan/sum_gj.dat"
```

### LLM 配置

#### OpenAI API
在 `LLM_API.py` 中配置：
```python
OPENAI_API_KEY = "your-api-key"
OPENAI_API_BASE = "https://api.openai.com/v1"
```

#### 本地模型（如 qwen3:235b）
在 `LLM_API_KJY.py` 中配置本地模型接口。

### 覆盖率配置

覆盖率相关路径：
- `--coverage_filename_origin`: 原始覆盖率文件路径
- `--coverage_filename_later`: 后续覆盖率文件路径
- `--global_annotated_dir`: 全局 annotated 目录

## 📁 项目结构

```
ChipFuzzer/
├── xiangshan_fuzzing.py      # 主程序入口
├── global_coverage.py         # 全局覆盖率管理
├── agent_memory.py            # Agent 记忆系统
├── code_analyzer.py           # 代码分析器
├── asm_validator.py           # 汇编代码验证器
├── spec_analyzer.py           # SPEC 文件分析器
├── prompt.py                  # LLM prompt 模板
├── LLM_API.py                # OpenAI API 接口
├── LLM_API_KJY.py            # 本地模型 API 接口
├── config.py                 # 配置文件
│
├── chipfuzz/                  # Web UI
│   ├── index.html            # 前端页面
│   ├── assets/               # 静态资源
│   │   ├── main.js          # 前端逻辑
│   │   └── style.css        # 样式文件
│   └── server/               # 后端服务
│       ├── app.py           # FastAPI 应用
│       └── requirements.txt # Python 依赖
│
├── GJ_Success_Seed/          # 成功测试用例
│   ├── *.S                  # 汇编文件
│   ├── *.bin                # 二进制文件
│   └── *.txt                # 用例报告
│
├── GJ_log/                   # 日志和统计
│   ├── *.log                # 运行日志
│   ├── statistics_*.json    # 统计数据
│   └── module_report_*.txt  # 模块报告
│
└── agent_memory/             # Agent 记忆数据
    └── *_memory.json        # 各模块的记忆文件
```

## 🛠️ 技术栈

- **Python 3.8+**: 主要开发语言
- **FastAPI**: Web 后端框架
- **Verilator**: 硬件仿真和覆盖率分析
- **Chart.js**: 前端图表可视化
- **RISC-V 工具链**: 编译和链接
- **LLM APIs**: OpenAI / 本地模型接口

## 🔍 工作流程

1. **初始化**
   - 读取未覆盖代码
   - 初始化 Agent Memory
   - 加载 SPEC 文件（如果启用）

2. **生成阶段**
   - LLM 分析未覆盖代码
   - 生成 RISC-V 汇编测试用例
   - 验证汇编语法

3. **编译阶段**
   - 使用 RISC-V 工具链编译
   - 如果失败，调用 LLM 修复

4. **执行阶段**
   - 运行模拟器执行测试用例
   - 收集覆盖率数据（`.dat` 文件）

5. **分析阶段**
   - 合并覆盖率数据
   - 更新全局覆盖率统计
   - 判断是否提升覆盖率

6. **保存阶段**
   - 如果提升覆盖率，保存为成功用例
   - 更新 Agent Memory
   - 生成用例报告

## 📊 输出文件说明

### 成功用例文件
- `GJ_Success_Seed/{module}_asm_{timestamp}_{hash}.S`: 汇编源代码
- `GJ_Success_Seed/{module}_asm_{timestamp}_{hash}.bin`: 编译后的二进制
- `GJ_Success_Seed/{module}_asm_{timestamp}_{hash}.txt`: 用例报告

### 统计文件
- `GJ_log/statistics_{timestamp}.json`: 统计数据（LLM 次数、成功率等）
- `GJ_log/module_report_{timestamp}.txt`: 模块测试报告

### 覆盖率文件
- `/root/XiangShan/sum_gj.dat`: 累积覆盖率数据
- `/root/XiangShan/coverage.info`: 覆盖率信息文件
- `/root/XiangShan/logs_global/annotated/`: 带注释的源代码

## ❓ 常见问题

### Q: 编译失败怎么办？
A: 框架会自动调用 LLM 修复代码，最多尝试 3 次。如果仍然失败，会跳过该用例。

### Q: 如何查看覆盖率报告？
A: 使用 `genhtml` 工具：
```bash
cd /root/XiangShan
genhtml coverage.info --output-directory coverage_report
```

### Q: LLM 生成次数不更新？
A: 确保统计数据文件正常生成，检查 `GJ_log/statistics_*.json` 文件。

### Q: Web UI 无法连接？
A: 检查：
1. 后端服务是否运行（`ps aux | grep uvicorn`）
2. API Base 配置是否正确（不要包含 `/api` 后缀）
3. Nginx 配置（如果使用）是否正确

### Q: Fresh 模式覆盖率异常？
A: Fresh 模式会重置基线，首次运行后基线会自动设置为第一次测试的结果。

## 🤝 贡献指南

欢迎贡献代码！请遵循以下步骤：

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📝 更新日志

### v1.0.0 (2026-01-27)
- ✅ 初始版本发布
- ✅ 完整的 LLM 驱动测试用例生成
- ✅ 全局覆盖率管理系统
- ✅ Web UI 实时监控
- ✅ Agent Memory 系统
- ✅ SPEC 文件集成
- ✅ 统计数据和可视化

## 📄 许可证

本项目采用 MIT 许可证。详情请参阅 LICENSE 文件。

## 📧 联系方式

- GitHub: [@fireceW](https://github.com/fireceW)
- 项目地址: https://github.com/fireceW/ChipFuzzer



---

**注意**: 本项目仍在积极开发中，API 和功能可能会有变化。建议在生产环境使用前充分测试。
