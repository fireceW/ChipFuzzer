# SPEC File Integration

## Overview

The SPEC integration system analyzes processor specification files, such as `SpecBlock_v4.sv` and `r4_qds_spec.sv`, extracts module interfaces and signal definitions, and adds this information to LLM prompts. The goal is to help the LLM generate more precise testcases for modules whose behavior is described by auxiliary SPEC files.

## Features

### Automatic SPEC Parsing

- Search location: all `*spec*.sv` files under `/root/XiangShan/build/rtl/`.
- Extracted information:
  - Module names
  - Input and output ports
  - Signal widths
  - Submodule instances

### Signal Information Extraction

- Identifies all input ports and output ports.
- Parses signal widths such as `[4:0]` and `[8:0]`.
- Associates uncovered-code signals with matching SPEC signals when possible.

### Matching Strategy

- Exact module-name matching.
- Fuzzy matching for module names with generated suffixes.
- Signal-name extraction from uncovered RTL code.

### Test Hint Generation

- Includes interface information in the prompt.
- Suggests value ranges based on signal widths.
- Provides targeted testing hints derived from SPEC information.

## Automatic Use

SPEC integration is invoked by the testcase generation flow when `--use_spec` is enabled. The system:

1. Identifies the target module.
2. Looks up a matching SPEC module from the cache.
3. Formats the SPEC information as prompt context.
4. Guides the LLM to generate testcases using this context.

## Manual Example

```python
from spec_analyzer import get_module_spec_hints, get_spec_analyzer

module_name = "SpecBlock_v4"
uncovered_code = """
  if (io_q_j == 5'h1f) begin
    ...
  end
"""

hints = get_module_spec_hints(module_name, uncovered_code)
print(hints)

analyzer = get_spec_analyzer()
for spec in analyzer.spec_cache.values():
    print(spec.name)
```

## Prompt Format

SPEC information is formatted as a compact prompt section containing:

- Module name
- Input and output signals
- Signal widths
- Submodules
- Key signals found in the uncovered RTL
- Suggested testcase directions

## Benefits

- Makes the LLM aware of module interfaces.
- Reduces invalid guesses about signal width and value ranges.
- Provides design-specific hints without manually writing a separate prompt for each module.
- Reuses parsed SPEC data through an in-memory cache.

## Extending the Parser

- Add new SPEC files under the configured RTL directory.
- Modify `_parse_spec_file` in `spec_analyzer.py` to support additional syntax.
- Modify `generate_test_hints` to change the prompt format.

## Implementation Notes

- SPEC files are loaded lazily on first use.
- Parsed SPEC data is cached in memory.
- The matching strategy is intentionally conservative to avoid injecting unrelated module context.
