# Project agent entrypoint

Resolve the shared library from `AI_SKILLS_HOME` (absolute ai_skills repository path) when set. Otherwise, walk from the actual working project upward to the nearest `ai_skills/skills/pipelines.json`; in ai_skills itself use its own catalog. Read GLOBAL_RULES.md beside that repository when present. If no shared rules are available, read this project's GLOBAL_RULES.md when present. Do not hard-code a PC-specific path or assume a Git parent is automatically loaded.

Read PROJECT_RULES.md if present for actual project facts and mandatory controls. Locate shared skills through the library's skills/pipelines.json and read only needed skills. Keep the actual project root separate from the shared library; run tools from the project directory or pass --project-root / AI_PROJECT_ROOT. User-level skill links provide automatic discovery; this file alone does not register skills. Preserve local customizations and use explicit snapshots for fixed-version projects.

Follow higher-priority runtime instructions and the user's current scope and authorization.

The main agent decomposes the request, delegates only useful independent work, integrates results and verifies completion. Use one writer per shared file and respect available runtime capacity. Keep simple work in this conversation; persist a compact task record when resumption or coordination needs it.

Read [policies/TRACEABILITY.md](policies/TRACEABILITY.md) only when tracked mode or existing project requirements apply. Do not create logs, role files or a project questionnaire merely to begin an ordinary task.

When adding this entrypoint to an existing repository, merge applicable guidance into its existing AGENTS.md; do not replace repository-specific instructions.
