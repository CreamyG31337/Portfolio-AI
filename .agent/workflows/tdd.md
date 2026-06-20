---
description: Workflow for implementing features using Test-Driven Development (Red-Green-Refactor)
---

# TDD Workflow

This workflow ensures robust code by writing tests *before* implementation.

## 1. Red Phase (Write Test)
**Goal**: Define the expected behavior.

- **Backend**: Create a new test file or add a function to `tests/`.
  - Example: `tests/test_scheduler.py`
  - Mock dependencies using `base_fixture` patterns.
- **Frontend**: Create a `*.test.ts` file next to the source.
  - Example: `web_dashboard/src/js/utils.test.ts`

**Action**: Run the test.
> It **MUST** fail. If it passes, verify your assumptions.

## 2. Green Phase (Implement)
**Goal**: Make the test pass.

- Write the *minimum* amount of code required.
- Do not worry about perfection or optimization yet.

**Action**: Run the test.
> It **MUST** pass.

## 3. Refactor Phase (Cleanup)
**Goal**: Improve code quality.

- Remove duplication.
- Improve naming.
- Optimize performance.

**Action**: Run the test.
> It **MUST** still pass.

## Test Selection

**CRITICAL**: Always run the correct test suite based on what code you're modifying. See `AGENTS.md` section "Test-Driven Development (TDD) and Test Selection" for detailed guidance.

**Quick Reference:**
- **Flask code** (`web_dashboard/app.py`, `web_dashboard/routes/*.py`, etc.) → Run Flask tests
- **Console app code** (`trading_script.py`, `portfolio/*.py`, etc.) → Run console app tests

## Commands

**Flask Tests:**
- **All Flask tests**: `python -m pytest tests/test_flask_*.py -v` (with root venv activated)
- **Single Flask test**: `python -m pytest tests/test_flask_routes.py -v` (with root venv activated)

**Console App Tests:**
- **All console tests**: `python -m pytest tests/ -v -k "not flask"` (with root venv activated)
- **Using test runner**: `python run_tests.py all`
- **Single test**: `python -m pytest tests/test_specific_file.py -v` (with root venv activated)

**Frontend Tests:**
- **TypeScript tests**: `cd web_dashboard && npx vitest run path/to/test.ts`
