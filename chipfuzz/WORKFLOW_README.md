# ChipFuzzer Workflow Visualization

## Overview

The workflow visualization shows the full ChipFuzzer loop, from uncovered-code analysis to LLM testcase generation, compilation, simulation, coverage collection, result analysis, and successful seed preservation.

## Workflow Steps

1. Analyze uncovered RTL code.
2. Generate a RISC-V assembly testcase with the LLM.
3. Compile the assembly file into an executable artifact.
4. Run the testcase in the simulator.
5. Collect and merge coverage data.
6. Decide whether coverage improved.
7. Save successful testcases to the seed corpus.
8. Continue with the next uncovered target.

## Runtime Display

When a fuzzing task is running, the visualization highlights the current step based on backend log messages:

- The active step is highlighted.
- Edges show flow animation.
- Completed steps remain visible for progress tracking.

## Reset and Export

- The reset button restarts the demo animation.
- The export button captures the workflow as a PNG image for reports or presentations.

## Implementation

- `chipfuzz/assets/workflow.js`: workflow logic.
- `chipfuzz/assets/style.css`: workflow styling.
- `chipfuzz/index.html`: workflow container.

## Notes

The visualization is a monitoring aid. It does not change the fuzzing algorithm or the backend execution state.
