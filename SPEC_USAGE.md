# SPEC 文件利用系统

## 概述

SPEC 文件利用系统通过分析香山处理器的 spec 文件（如 `SpecBlock_v4.sv`、`r4_qds_spec.sv` 等），提取模块接口、信号定义等关键信息，并将这些信息整合到 LLM prompt 中，帮助生成更精准的测试用例。

## 功能特性

### 1. 自动解析 SPEC 文件
- **位置**: `/root/XiangShan/build/rtl/` 目录下的所有 `*spec*.sv` 文件
- **提取内容**:
  - 模块名
  - 输入/输出信号列表
  - 信号宽度信息
  - 子模块实例

### 2. 信号信息提取
- **输入信号**: 识别所有 `input` 端口及其宽度
- **输出信号**: 识别所有 `output` 端口及其宽度
- **信号宽度**: 解析如 `[4:0]`、`[8:0]` 等宽度定义

### 3. 智能匹配
- **精确匹配**: 模块名完全匹配
- **模糊匹配**: 处理带后缀的模块（如 `L2DataStorage_1`）
- **信号匹配**: 从未覆盖代码中提取信号名，并在 spec 中查找对应信息

### 4. 测试建议生成
- **接口信息**: 显示模块的输入输出信号
- **信号宽度**: 根据信号宽度给出测试值范围建议
- **测试策略**: 基于 spec 信息生成针对性的测试建议

## 使用方式

### 自动集成
系统已自动集成到测试生成流程中，无需手动调用。当生成测试用例时，系统会：

1. **识别模块**: 从当前测试的模块名或未覆盖代码中识别模块
2. **查找 SPEC**: 在 spec 缓存中查找对应的模块规格
3. **生成提示**: 将 spec 信息格式化为提示添加到 prompt 中
4. **指导生成**: LLM 根据 spec 信息生成更精准的测试用例

### 手动使用示例

```python
from spec_analyzer import get_module_spec_hints, get_spec_analyzer

# 获取模块的 spec 提示
module_name = "SpecBlock_v4"
uncovered_code = """
  if (io_q_j[0]) begin
    io_nxt_spec_0_0_0 <= io_cons_0_0;
  end
"""

hints = get_module_spec_hints(module_name, uncovered_code)
print(hints)

# 直接访问 spec 分析器
analyzer = get_spec_analyzer()
spec = analyzer.get_module_spec("SpecBlock_v4")
if spec:
    print(f"模块: {spec.name}")
    print(f"输入信号数: {len([s for s in spec.signals if s.direction == 'input'])}")
    print(f"输出信号数: {len([s for s in spec.signals if s.direction == 'output'])}")
```

## 输出格式

在 LLM prompt 中，spec 信息会以以下格式出现：

```
## 📋 模块规格信息 (SpecBlock_v4)

**输入信号 (25 个):**
  - `io_q_j` [4:0] (input)
  - `io_cons_0_0` [8:0] (input)
  - `io_cons_0_1` [8:0] (input)
  ...

**输出信号 (20 个):**
  - `io_nxt_spec_0_0_0` [8:0] (output)
  - `io_nxt_spec_0_0_1` [8:0] (output)
  ...

**子模块:** CSA3_2_3992, SignDec

**未覆盖代码中的关键信号:**
  - `io_q_j`: input, 宽度 4:0
  - `io_cons_0_0`: input, 宽度 8:0

**测试建议:**
  1. 通过 RISC-V 指令设置输入信号的值
  2. 测试不同输入组合以触发所有分支
  3. `io_q_j` 是 5 位信号，测试值范围: 0 到 31
  4. `io_cons_0_0` 是 9 位信号，测试值范围: 0 到 511
```

## 优势

### 1. 提高准确性
- **接口感知**: LLM 知道模块有哪些输入输出信号
- **宽度信息**: 了解信号宽度，生成合适的测试值
- **功能理解**: 通过子模块信息理解模块功能

### 2. 减少无效尝试
- **边界值**: 根据信号宽度自动计算边界值
- **组合测试**: 知道输入信号数量，可以生成更全面的组合
- **针对性**: 针对特定信号生成测试，而不是盲目尝试

### 3. 知识积累
- **自动加载**: 启动时自动加载所有 spec 文件
- **缓存机制**: spec 信息缓存在内存中，快速访问
- **扩展性**: 新增 spec 文件会自动被识别和加载

## 当前加载的 SPEC 模块

运行以下命令查看已加载的 spec 模块：

```bash
python3 -c "from spec_analyzer import get_spec_analyzer; analyzer = get_spec_analyzer(); print('已加载模块:', list(analyzer.spec_cache.keys()))"
```

当前已加载的模块：
- `r4_qds_spec`
- `r4_qds_v2_spec`
- `SpecBlock_v4`

## 扩展

### 添加新的 SPEC 文件
只需将 spec 文件放到 `/root/XiangShan/build/rtl/` 目录下，文件名包含 `spec` 即可自动加载。

### 自定义解析规则
修改 `spec_analyzer.py` 中的 `_parse_spec_file` 方法可以自定义解析规则。

### 增强提示信息
修改 `generate_test_hints` 方法可以自定义提示信息的格式和内容。

## 技术细节

### 信号提取正则表达式
```python
port_pattern = r'(input|output|inout)\s+(?:\[([^\]]+)\])?\s*(\w+)'
```

### 模块匹配策略
1. 精确匹配模块名
2. 模糊匹配（处理带后缀的情况）
3. 从代码中提取模块名（通过 `.sv` 文件名）

### 性能优化
- **启动时加载**: 所有 spec 文件在首次使用时一次性加载
- **内存缓存**: spec 信息缓存在内存中，避免重复解析
- **懒加载**: 只有在需要时才解析 spec 文件
