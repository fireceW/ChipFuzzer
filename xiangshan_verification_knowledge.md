# XiangShan Verification Knowledge Base

This note summarizes verification-relevant information collected from XiangShan RISC-V processor SPEC files and RTL code. It is used as optional background context for testcase generation.

## SpecBlock Module

`SpecBlock_v4` is a speculation-related block used in division normalization logic.

Key signals:

- `io_q_j[4:0]`: quotient-selection signal.
- `io_cons_*`: constraint inputs.
- Outputs: normalized results.

Verification targets:

1. Exercise all possible values of `io_q_j`.
2. Try different combinations of `io_cons` signals.
3. Cover alternative datapath normalization cases.

## Important XiangShan Modules

L2-cache-related modules include:

- `L2Cache`
- `L2DataStorage`
- `L2Directory`
- `L2TLB`
- `L2TLBWrapper`
- `L2TlbPrefetch`
- `L2Top`

Relevant verification scenarios include cache coherence, TLB management, and prefetch behavior.

## RISC-V Instruction Coverage Strategy

Basic RV64I groups:

- Arithmetic: `add`, `sub`, `addi`, `slli`, `srai`
- Logic: `and`, `or`, `xor`, `andi`, `ori`, `xori`
- Comparison: `slt`, `sltu`, `slti`, `sltiu`
- Branch: `beq`, `bne`, `blt`, `bge`, `bltu`, `bgeu`
- Jump: `jal`, `jalr`
- Load/store: `lb`, `lh`, `lw`, `ld`, `sb`, `sh`, `sw`, `sd`

Extension groups:

- M extension: multiply and divide instructions.
- A extension: atomic instructions.
- F/D extensions: floating-point instructions.
- C extension: compressed instructions.

## Verification Focus

- Pipeline hazards: data, control, and structural hazards.
- Exception handling: illegal instructions, divide-by-zero cases, page faults, and privilege transitions.
- Privilege modes: user, supervisor, and machine mode.
- Cache behavior: hits, misses, replacement, and coherence interactions.
- TLB behavior: page-table walks, replacement, and ASID handling.

## Testcase Generation Hints

SPEC-aware generation should:

1. Analyze module inputs and outputs.
2. Identify control predicates and state transitions.
3. Generate boundary values for narrow signals.
4. Combine multiple input conditions when branches require correlated state.

Example strategy for `SpecBlock_v4`:

```assembly
# Sweep representative io_q_j values.
li t0, 0
li t1, 31
```

## Coverage Targets

Suggested structural targets:

- Line coverage above 80%.
- Branch coverage above 75%.
- Condition coverage above 70%.
- State-related coverage above 80% when explicit state machines are present.

## Toolchain

- Verilator for simulation and coverage collection.
- `verilator_coverage` for coverage merging and reporting.
- `genhtml` for HTML coverage reports.
- LLM-guided generation with optional agent memory.

## Continuous Improvement

The knowledge base can be extended with:

- Module-specific verification points.
- Successful testcase patterns.
- Common error patterns and correction hints.
