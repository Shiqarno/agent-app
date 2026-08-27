# Project Instructions

## Project

This is a 3-tier web application:

- Frontend: web client
- Backend: Python
- Database: PostgreSQL

## Development Principles

- Prefer simple solutions over unnecessary complexity.
- Do not introduce new dependencies unless necessary.
- Do not modify unrelated code.
- Do not refactor code unless the task requires it.
- Preserve existing architecture unless explicitly instructed otherwise.

## Agent Workflow

Before making changes:

1. Understand the relevant part of the codebase.
2. Identify the files that need to change.
3. State a short implementation plan.

During implementation:

- Make the smallest reasonable change.
- Do not change public APIs unless explicitly required.
- Do not delete or weaken tests to make them pass.

After implementation:

1. Run relevant tests.
2. Run static checks.
3. Report any failures honestly.
4. Summarize what changed.

## Important

If requirements are ambiguous or a change requires an architectural decision, stop and ask for clarification instead of guessing.