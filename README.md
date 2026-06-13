# ChipFuzzer

ChipFuzzer is an LLM-driven hardware fuzzing framework for RTL verification. It targets RISC-V processors and related hardware designs by generating, validating, and executing assembly testcases to improve RTL coverage and expose difficult-to-reach design behavior.

## Overview

ChipFuzzer combines:

- LLM-guided testcase generation for RISC-V assembly programs.
- RTL coverage analysis for identifying uncovered code regions.
- Automatic compilation, simulation, and coverage feedback.
- Optional agent memory for reusing successful generation patterns.
- Optional SPEC-aware analysis for extracting module interfaces and signal widths.
- A lightweight Web UI for monitoring fuzzing runs and coverage statistics.

The framework is designed to reduce manual effort in testcase construction and to help verification engineers target uncovered RTL control paths more directly.

## Main Features

### LLM-Driven Test Generation

- Supports API-based and local LLM backends.
- Generates targeted RISC-V assembly from uncovered RTL code and optional SPEC information.
- Invokes correction steps when generated assembly fails to compile.
- Supports multiple testcase strategies, including boundary-value tests, CSR tests, and memory-access tests.

### Coverage Management

- Tracks cumulative RTL coverage across fuzzing iterations.
- Supports module-level coverage analysis.
- Keeps only testcases that improve coverage.
- Provides L2 module group summaries for modules such as L2Cache and L2TLB.

### Agent Memory

- Records successful and failed LLM interactions.
- Retrieves relevant prior examples for similar uncovered code.
- Learns recurring instruction patterns and common error patterns.

### SPEC Integration

- Parses `*spec*.sv` files when available.
- Extracts module ports, signal widths, and submodule information.
- Adds SPEC-derived hints to LLM prompts for more precise testcase generation.

### Web UI

- Streams or polls runtime logs.
- Visualizes coverage growth.
- Displays generation, compilation, and simulation statistics.
- Lists successful testcase artifacts.

## Requirements

- Python 3.8+
- RISC-V toolchain, such as GCC and objdump
- Verilator for coverage collection
- A target hardware project and simulator
- Access to an LLM backend

## Quick Start

### 1. Clone the artifact

Use the anonymous artifact link provided with the submission, or clone the local artifact copy used in your environment.

```bash
git clone <anonymous-artifact-url> ChipFuzzer
cd ChipFuzzer
```

### 2. Install Python dependencies

```bash
pip install -r chipfuzz/server/requirements.txt
```

### 3. Configure paths

Edit `config.py` or pass command-line arguments to configure:

- Target project path
- Coverage data paths
- Testcase output directory
- LLM backend settings

### 4. Start the optional Web API

```bash
cd chipfuzz/server
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

## Usage

### Test a Single Module

```bash
python <backend-script>.py \
    --module Bku \
    --model qwen3:235b \
    --mode continue \
    --max_iterations 20
```

### Run Automatic Module Selection

```bash
python <backend-script>.py \
    --module auto \
    --num 5 \
    --model qwen3:235b \
    --mode fresh \
    --auto_switch
```

### Enable SPEC-Aware Prompting

```bash
python <backend-script>.py \
    --module L2TLB \
    --model qwen3:235b \
    --use_spec \
    --max_iterations 30
```

## Common Arguments

| Argument | Description | Default |
| --- | --- | --- |
| `--module` | Target module name, or `auto` for automatic selection | Required |
| `--model` | LLM model name | Required |
| `--mode` | `continue` to reuse prior coverage, or `fresh` to reset coverage | `continue` |
| `--max_iterations` | Maximum generation attempts per module | `20` |
| `--num` | Number of modules in automatic mode | `1` |
| `--auto_switch` | Automatically switch modules after the stopping condition is met | `False` |
| `--use_spec` | Enable SPEC-aware analysis | `False` |
| `--run_existing_seeds` | Re-run existing successful seeds | `False` |

## Running Modes

### Continue Mode

Continue mode reuses existing coverage files, such as `sum_gj.dat`, and performs incremental coverage improvement.

### Fresh Mode

Fresh mode creates a new coverage baseline and is useful for clean benchmark runs.

## Web UI

### Start the Backend API

```bash
cd chipfuzz/server
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Open the Frontend

Open `chipfuzz/index.html` directly in a browser, or serve the `chipfuzz/` directory with a static file server.

### Optional Nginx Proxy

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080/api/;
    proxy_http_version 1.1;
    proxy_buffering off;
}
```

## Configuration

Main path settings are defined in `config.py`:

```python
project_root = "/path/to/target_project/"
testcase_dir = "/path/to/testcases"
global_annotated_dir = "/path/to/annotated"
sum_dat_file = "/path/to/sum_gj.dat"
```

LLM backend settings are configured in `LLM_API.py` or `LLM_API_KJY.py`, depending on the backend used.

## Repository Layout

```text
ChipFuzzer/
|-- global_coverage.py          # Global coverage manager
|-- agent_memory.py             # Agent memory system
|-- code_analyzer.py            # RTL code analysis helpers
|-- asm_validator.py            # RISC-V assembly validator
|-- spec_analyzer.py            # SPEC file analyzer
|-- prompt.py                   # LLM prompt templates
|-- LLM_API.py                  # API-based LLM backend
|-- LLM_API_KJY.py              # Local LLM backend
|-- config.py                   # Path and runtime configuration
|-- chipfuzz/                   # Web UI and Web API
|   |-- index.html
|   |-- assets/
|   `-- server/
|-- llm_result/                 # Historical generated outputs
`-- agent_memory/               # Persistent memory data
```

## Output Files

- `GJ_Success_Seed/{module}_asm_{timestamp}_{hash}.S`: generated assembly testcase.
- `GJ_Success_Seed/{module}_asm_{timestamp}_{hash}.bin`: compiled binary.
- `GJ_Success_Seed/{module}_asm_{timestamp}_{hash}.txt`: testcase report.
- `GJ_log/statistics_{timestamp}.json`: run statistics.
- `GJ_log/module_report_{timestamp}.txt`: module-level report.
- `sum_gj.dat`: cumulative coverage data.
- `coverage.info`: coverage summary file.
- `annotated/`: annotated coverage output.

## Troubleshooting

### Compilation fails

The framework invokes the correction pipeline for generated assembly. If correction still fails after the iteration limit, the testcase is discarded and the next generation attempt starts.

### Coverage reports are missing

Check that the target simulator produces Verilator coverage data and that the configured coverage paths point to the expected files.

### The Web UI cannot connect

Check that the backend API is running, the API base URL is correct, and any Nginx proxy is forwarding `/api/` requests correctly.

## License

This artifact is released for research and review purposes. See the license file if one is included in the artifact package.

## Note

APIs and paths may need to be adapted to the local simulator and target project. Please test the configuration before running large-scale fuzzing campaigns.
