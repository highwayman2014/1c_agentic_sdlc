# Pi и Claude Code

Проверено 30.10.2026: установлен `pi-mcp-adapter 7.0.0` и Claude Code `2.1.312`.
В настройках pi пакет адаптера подключён, встроенный MCP отключён через `-builtin:mcp`.
Готовые файлы рассчитаны на эту установку.

## Файлы для рабочей папки

| Клиент | Файл в папке проекта или worktree | Содержание |
|---|---|---|
| Claude Code | `.mcp.json` | Полный набор серверов с явными типами `stdio` и `http` |
| Pi с pi-mcp-adapter | `.pi/mcp-adapter.json` | Полный набор серверов, lifecycle и таймауты адаптера |
| Codex | `.codex/config.toml` | Анализатор текущей папки и проектная wiki; общие сервисы наследуются |

В каждом JSON есть справка платформы, OpenViking, Atlassian, обе wiki и анализатор.
Для ЗУП подключаются три анализатора вместо одного.
Команды, источники и кеши совпадают между клиентами.
Ключи читает общий `scripts/mcp_profile.py` из локальных env-файлов.
Отдельная установка анализатора для нового клиента не нужна.

Готовые файлы:

- СММ: [Claude Code](configs/projects/smm_auto/.mcp.json), [pi](configs/projects/smm_auto/.pi/mcp-adapter.json).
- КШР: [Claude Code](configs/projects/carsh_auto/.mcp.json), [pi](configs/projects/carsh_auto/.pi/mcp-adapter.json).
- ЗУП: [Claude Code](configs/projects/zup/.mcp.json), [pi](configs/projects/zup/.pi/mcp-adapter.json).
- БП: [Claude Code](configs/projects/bp/.mcp.json), [pi](configs/projects/bp/.pi/mcp-adapter.json).
- DEV1C-33021: [Claude Code](configs/worktrees/smm_auto-dev1c-33021-spisanie-tmc/.mcp.json), [pi](configs/worktrees/smm_auto-dev1c-33021-spisanie-tmc/.pi/mcp-adapter.json).

В worktree анализатор читает исходники задачи и использует её отдельный кеш.
Проектная wiki указывает на основную папку проекта.
Путь готового примера другой задачи не копируй в новый worktree: передай установщику фактическую папку.

## Применение

Выполняй команды из `D:\repository\1c_agentic_sdlc`.
Сначала проверь пути:

```powershell
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --check
```

Выбери клиент:

```powershell
# Только pi: записать .pi/mcp-adapter.json
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --client pi --apply

# Только Claude Code: записать .mcp.json
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --client claude --apply

# Все три клиента; общие профили Codex уже должны быть установлены
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --client all --apply
```

Для обычной ветки передай основную рабочую папку.
Без `--client` сохраняется прежний режим Codex: нативный TOML и общий `.mcp.json`.
`--apply-shared` управляет только общими профилями Codex.
Pi и Claude Code получают полный набор из проектного файла и не требуют глобального конфига Codex.
Локальные env-файлы авторизации должны быть уже заполнены; см. [основную инструкцию](README.md#общая-установка-и-локальные-секреты).

Для просмотра используй `--output <каталог>`: он всегда создаёт файлы всех трёх клиентов.
При применении сохраняются посторонние серверы и настройки JSON, включая настройки адаптера.
Неизвестные составы анализаторов требуют ручной сверки до замены.
Резервные копии находятся вне Git, в пользовательском `.config/1c-agentic-sdlc/backups`.

## Поведение pi

Для серверов выбран `lifecycle="lazy-keep-alive"`.
Адаптер подключает их по обращению; при отсутствии кеша метаданных он также может подключиться для получения списка инструментов.
После подключения процесс не завершается по таймеру простоя адаптера.
Таймаут запроса — `120000` миллисекунд.
Broker анализатора дополнительно сохраняет backend 12 часов после отключения клиентов.
Это не исправляет ошибку графа или холодный старт после перезагрузки Windows.

Адаптер также читает общий `.mcp.json`.
Его собственный `.pi/mcp-adapter.json` имеет более высокий приоритет; одинаковые имена серверов объединяются.
Оба файла создавай одним установщиком, чтобы их пути не расходились.
Настройки `directTools`, `excludeTools` и общей политики разрешений установщик не добавляет; действуют настройки адаптера пользователя.

В pi выполни `/reload`, затем проверь `/mcp-adapter`.
Для проектных серверов действуют доверие и подтверждения самого клиента; они не отключаются этими файлами.
Команда `pi mcp list` относится к встроенному MCP и не проверяет собственный файл адаптера.

Если перейдёшь на встроенный MCP pi, потребуется отдельная миграция:
он использует `.pi/mcp.json` и `~/.pi/agent/mcp.json`, а не `mcp-adapter.json`.
Не включай два MCP-расширения ради загрузки этих файлов.

## Поведение Claude Code

Запускай `claude` из папки проекта или worktree.
Проверь серверы через `/mcp`; Claude Code может запросить доверие к проектному `.mcp.json`.
Обязательное поле `type="http"` уже добавлено к OpenViking.
Нативные таймауты Codex и поля lifecycle адаптера в этот файл не попадают.

Фрагменты для необязательной общей настройки:
[Claude user MCP](configs/shared/claude/user-mcp.json) и [pi adapter](configs/shared/pi/mcp-adapter.json).
В них только четыре общих сервиса.
Это готовые определения MCP, а не замена всего `~/.claude.json` или конфигурации адаптера.
Объединяй `mcpServers` с существующими настройками; проектные файлы уже содержат эти сервисы.
Установщик не переписывает пользовательские файлы Claude и pi.

Подключение сервера не разрешает операции в ИБ.
Глобальные и сторонние серверы могут добавляться клиентом отдельно от этих файлов.
После подключения проверь корни, wiki и готовность подсистем по [общему списку](README.md#проверить-подключение).

Источники: [Claude Code MCP](https://code.claude.com/docs/en/mcp),
[pi-mcp-adapter configuration](https://github.com/nicobailon/pi-mcp-adapter/blob/main/docs/configuration.md),
[встроенный MCP pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/mcp.md).
