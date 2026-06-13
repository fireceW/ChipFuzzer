# Agent Memory System

## Overview

The agent memory system stores historical LLM interactions and reuses them as context for future testcase generation. It is intended to improve generation quality by allowing the fuzzer to learn from prior successful and failed attempts.

## Core Functions

### Interaction History

- Records each LLM call and its associated context.
- Marks whether the generated testcase compiled, executed, and improved coverage.
- Stores compilation and execution errors for later analysis.

### Code Pattern Learning

- Extracts recurring instruction-sequence patterns from successful assembly testcases.
- Tracks success and failure counts for each pattern.
- Stores representative examples for prompt augmentation.

### Error Pattern Library

- Classifies common errors such as register errors, syntax errors, undefined symbols, and timeouts.
- Tracks how often each error type occurs.
- Adds reminders to prompts so that the LLM avoids repeated mistakes.

### Context Retrieval

- Matches similar uncovered code by using normalized code hashes.
- Retrieves relevant successful and failed cases.
- Adds a compact memory summary to the generation prompt.

## Integration

The memory manager can be initialized inside the module-level fuzzing session:

```python
self.agent_memory = get_agent_memory(module_name)
```

## When Memory Is Recorded

The system records memory when:

1. A testcase is generated.
2. Compilation succeeds or fails.
3. Coverage improves.
4. A correction attempt is made.
5. An analysis prompt produces useful feedback.

## Memory Retrieval

During prompt construction, the system:

1. Looks for previous interactions with similar uncovered code.
2. Retrieves high-success instruction patterns.
3. Adds recent failure information to avoid repeated mistakes.
4. Builds a concise prompt context for the LLM.

## File Layout

```text
agent_memory.py          # Core implementation
agent_memory/            # Persistent memory directory
`-- {module}_memory.json # Per-module memory file
```

## Memory Format

Each memory entry stores:

- Timestamp
- Module name
- Hash of the uncovered code
- Prompt type
- Generated assembly
- Compilation status
- Coverage improvement status
- Error message, if any
- Strategy and feedback metadata

## Retention Policy

- Only the most recent 100 interaction records are persisted for each module.
- Pattern memories are retained, but each pattern stores only a small number of examples.
- Memory is saved periodically and again when the session finalizes.

## Performance Impact

- Memory lookup is in-memory and typically takes less than 10 ms.
- Per-module memory files are usually small.
- JSON serialization is used for portability and simple inspection.

## Future Improvements

- Vector-based retrieval for more accurate similarity matching.
- Cross-module sharing of successful patterns.
- Better ranking of strategies based on historical outcomes.
