# Настройки MCP

С 02.11.2026 СММ использует единый MCP `bsl`.
Он объединяет справку, анализ текущих исходников и live-инструменты.
Профили КШР, ЗУП и БП пока сохраняют прежний состав.

Глобальная установка для Codex, Claude Code и pi:

```powershell
python scripts/install_unified_bsl.py --apply
python scripts/configure_mcp.py --workspace D:\repository\1c\smm_auto --client all --apply-shared --apply
```

Обёртка выбирает ближайший TOML до границы Git.
В Codex проектный конфиг явно закрепляет `cwd`.
Вне проекта с TOML доступны справка и live-инструменты на пустом источнике.
Исполняемый app выбирается через указатель версии общего лаунчера.
Кеши рабочих папок разделяет штатный namespace анализатора.

Единый профиль не читает ключ провайдера эмбеддингов.
В 0.4.3 PostgreSQL overlay без embedder не подготавливается.
Поэтому поиск baseline может не учитывать текущие изменения.
Проверяй freshness/completeness каждого ответа.
Граф и диагностики проверяй отдельно от поиска.
Подробные правила: [настройка MCP](../.agents/skills/av-1c-agentic-sdlc/references/mcp.md)
и [индексы](../.agents/skills/av-1c-agentic-sdlc/references/search-index.md).


Назначение инструментов и порядок настройки описаны в навыке
[av-1c-agentic-sdlc](../.agents/skills/av-1c-agentic-sdlc/SKILL.md).
Готовые файлы находятся в [configs](configs).
