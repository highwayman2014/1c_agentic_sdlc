# MCP для pi и Claude Code

С 02.11.2026 СММ использует единый `bsl` вместо `bsl-reference`, `bsl-smm` и `bsl-smm-live`.
Установка: `python scripts/install_unified_bsl.py --apply`.
Применение проекта: `python scripts/configure_mcp.py --workspace <путь> --client all --apply-shared --apply`.
Другие проектные профили сохраняются до отдельной миграции.
Текущие правила: [mcp.md](../.agents/skills/av-1c-agentic-sdlc/references/mcp.md).


Настройка клиентов описана в навыке
[av-1c-agentic-sdlc](../.agents/skills/av-1c-agentic-sdlc/SKILL.md).
Используй раздел настройки MCP этого навыка.
