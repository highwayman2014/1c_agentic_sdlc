# Настройки MCP

Единый MCP `bsl` объединяет справку платформы, анализ исходников и live-инструменты.
Общие скрипты и навык не зависят от имени проекта.
Пути, состав исходников, подключения и политики запуска задаются конфигами.

| Файл | Назначение |
|---|---|
| `runtime.json` | Общая установка, каталоги кешей, лимиты ресурсов, сервисы и имена заменяемых серверов |
| `projects.json` | Ключи проектов, основные рабочие папки и режим профиля |
| `bsl-analyzer.toml` в проекте | CF, расширения и общий baseline |
| `baselines.json` | Источники baseline, роль credential helper и политика запуска |
| `baseline-service.json` | Docker-сервис baseline, каталог секретов и список схем |
| `onec-connections.json` | Именованные подключения к ИБ |
| `onec-credential-sources.json` | Ссылки на локальные учётные данные |

Для нового проекта добавь запись в `projects.json` и его TOML.
Примеры находятся в [examples](examples).
Файлы в [configs](configs) содержат готовые примеры конкретных окружений.
Адаптируй пути перед применением.
Секреты храни вне Git.

Команды выполняй из корня репозитория:

```powershell
python scripts/install_unified_bsl.py --apply
python scripts/configure_mcp.py --workspace <путь-проекта> --check
python scripts/configure_mcp.py --workspace <путь-проекта> --client all --apply-shared --apply
```

Без `--apply` глобальный установщик проверяет изменения без записи.
Генератор с `--output <каталог>` сохраняет готовые файлы без применения.
Проектная запись `unified=false` сохраняет прежние профили из `analyzers`.

Проверяй полноту overlay отдельно от готовности сервера.
Правила: [настройка MCP](../.agents/skills/av-1c-agentic-sdlc/references/mcp.md)
и [индексы](../.agents/skills/av-1c-agentic-sdlc/references/search-index.md).
Проверка общей установки и нового worktree: [порядок подключения](../.agents/skills/av-1c-agentic-sdlc/references/mcp-setup.md).
