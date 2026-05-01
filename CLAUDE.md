# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don’t keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy and Agent Teams
- Use subagents and agent teams liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents and agent teams
- For complex problems, throw more compute at it via subagents and agent teams
- One task per subagent and agent teams for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: “Would a staff engineer approve this?”
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask “Is there a more elegant way?”
- If a fix feels hacky: “Knowing everything I know now, implement the elegant solution”
- Skip this for simple, obvious fixes — don’t over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don’t ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items  
2. **Verify Plan**: Check in before starting implementation  
3. **Track Progress**: Mark items complete as you go  
4. **Explain Changes**: High-level summary at each step  
5. **Document Results**: Add review section to `tasks/todo.md`  
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections  

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what’s necessary. Avoid introducing bugs.


<!-- nervx:start -->
## nervx — codebase brain (auto-generated, do not edit this section)

nervx has pre-indexed this codebase into `.nervx/brain.db`. Use these commands
**before** falling back to grep/cat/Read — they return pre-computed answers in
tens to hundreds of tokens instead of thousands.

### EXPLORATION (use these BEFORE reading files)

| Command | What you get |
|---------|--------------|
| `nervx nav "<question>"` | ranked file:line results, call flows, read order, warnings |
| `nervx tree <file>` | structural overview of a file, ~150 tokens vs 4000 |
| `nervx peek <symbol>` | 50-token preview — signature, callees, caller count, test coverage, no source |

### READING (use these INSTEAD of cat/Read)

| Command | What you get |
|---------|--------------|
| `nervx read <symbol>` | source of one function/method |
| `nervx read <symbol> --context 1` | source of the symbol + everything it calls |
| `nervx read <symbol> --since <hash>` | returns "unchanged" (1 token) if the symbol hasn't been edited |

### QUICK ANSWERS (5–30 tokens each — use instead of reading source to verify)

| Command | Answers |
|---------|---------|
| `nervx ask exists <symbol>` | yes / no |
| `nervx ask signature <symbol>` | the function signature |
| `nervx ask calls <A> <B>` | does A call B directly? |
| `nervx ask imports <file>` | what this file imports |
| `nervx ask is-async <symbol>` | yes / no |
| `nervx ask returns-type <symbol>` | return type from signature |
| `nervx ask callers-count <symbol>` | integer |
| `nervx ask has-tests <symbol>` | yes / no + count |
| `nervx verify "A calls B"` | confirms or denies a call path (up to 6 hops) |

### ANALYSIS

| Command | When to use |
|---------|-------------|
| `nervx callers <symbol>` | who calls this function (focused) |
| `nervx blast-radius <symbol>` | full downstream impact (before refactors) |
| `nervx trace <from> <to>` | shortest call path between two symbols; add `--read` for source |
| `nervx find --dead` | unreferenced code (framework-aware) |
| `nervx find --no-tests --importance-gt 20` | critical untested code |
| `nervx flows [keyword]` | end-to-end execution paths |
| `nervx diff --days 7` | recent structural changes |

### TESTING

| Command | What you get |
|---------|--------------|
| `nervx run pytest [args]` | structured summary (~80 tokens vs 8000 of traceback) |
| `nervx run pytest --raw <run_id>` | retrieve the full cached raw output |

### CROSS-LANGUAGE

| Command | What you get |
|---------|--------------|
| `nervx string-refs <identifier>` | every file:line where this string literal appears, across all languages |

### WORKFLOW

1. Start with `nervx tree` / `nervx peek` to explore — NOT cat/Read.
2. Use `nervx ask` / `nervx verify` for quick verification — NOT reading source.
3. Use `nervx read --context 1` for targeted reading — NOT full file reads.
4. Use `nervx run pytest` for test results — NOT raw pytest output.
5. If nervx commands fail or return nothing useful, then fall back to grep/cat.

### Symbol ID format
`file_path::ClassName.method_name` or `file_path::function_name`. Example:
`server/main.py::handle_request`. Fuzzy matching is built in — short names like
`handle_request` usually resolve automatically, and ambiguous queries return a
"did you mean?" list.

### All commands support `--json`
Every output command accepts `--json` for machine-parseable output.

### Excluding files
Create a `.nervxignore` in the repo root (gitignore syntax) to exclude files.
Defaults already skip `__pycache__/`, `node_modules/`, `dist/`, `build/`,
`.venv/`, minified bundles, lockfiles, vendor dirs, etc.

NERVX.md contains the full architectural overview of this project.
<!-- nervx:end -->
