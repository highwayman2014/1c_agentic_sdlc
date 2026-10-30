# Нативный MCP pi и Claude Code

Проверено 30.10.2026: pi `1.4.0`, Claude Code `2.1.312`.
Пользователь выбрал встроенный MCP pi. Адаптер не требуется.

## Готовые файлы

| Клиент | Файл проекта или worktree |
|---|---|
| Pi | `.pi/mcp.json` |
| Claude Code | `.mcp.json` |
| Codex | `.codex/config.toml` |

Pi и Claude Code получают полный набор: справка платформы, OpenViking, Atlassian,
обе wiki и анализатор. В ЗУП подключаются три анализатора.
В worktree pi также отключает глобальный RLM через `enabled=false`.
В Codex общие сервисы наследуются из пользовательских настроек.

- СММ: [pi](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/smm_auto/.pi/mcp.json), [Claude Code](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/smm_auto/.mcp.json).
- КШР: [pi](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/carsh_auto/.pi/mcp.json), [Claude Code](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/carsh_auto/.mcp.json).
- ЗУП: [pi](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/zup/.pi/mcp.json), [Claude Code](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/zup/.mcp.json).
- БП: [pi](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/bp/.pi/mcp.json), [Claude Code](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/projects/bp/.mcp.json).
- DEV1C-33021: [pi](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/worktrees/smm_auto-dev1c-33021-spisanie-tmc/.pi/mcp.json), [Claude Code](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/worktrees/smm_auto-dev1c-33021-spisanie-tmc/.mcp.json).

Команды используют общую установку bsl-analyzer и локальные env-файлы авторизации.
Кеши разделены по рабочим папкам. Wiki проекта указывает на исходную папку.
Путь чужой задачи не копируй в новый worktree: передай установщику фактический путь.

## Перейти с адаптера на встроенный MCP pi

Из `D:\repository\1c_agentic_sdlc` проверь перенос:

```powershell
python scripts/migrate_pi_native.py
```

Примени перенос:

```powershell
python scripts/migrate_pi_native.py --apply
```

Скрипт переносит подключения из пользовательских файлов адаптера в
`C:\Users\shepa\.pi\agent\mcp.json`, сохраняя существующие нативные записи.
Он также добавляет отсутствующие общие профили из `configs/shared/pi/mcp.json`.
Существующие подключения и перенесённые адреса имеют приоритет над этими значениями.
Он сохраняет адреса и заголовки авторизации локально, переводит таймауты из
миллисекунд в секунды и переносит точные списки инструментов в `toolExposure`.
Импорты, OAuth, неизвестные параметры и неоднозначные фильтры требуют отдельной сверки:
в этих случаях скрипт останавливается до изменения настроек.

В пользовательском `settings.json` скрипт убирает `npm:pi-mcp-adapter`
из `packages`, снимает `-builtin:mcp` и включает `builtin:mcp`.
Остальные пакеты и настройки сохраняются. Установленный пакет и прежние
конфиги остаются на диске. Резервные копии находятся вне Git,
в `C:\Users\shepa\.config\1c-agentic-sdlc\backups`.
При повторном запуске существующие нативные подключения имеют приоритет.

Перезапусти pi. Встроенный MCP читает только пользовательский `mcp.json`
и `.pi/mcp.json` доверенного проекта. Старые `.mcp.json`,
`~/.config/mcp/mcp.json` и `mcp-adapter.json` он не читает.
Нативный режим не использует авторизацию из хранилища адаптера автоматически.

## Настроить проект или worktree

```powershell
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --check

# Нативный pi: записать .pi/mcp.json
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --client pi --apply

# Claude Code: записать .mcp.json
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --client claude --apply

# Все три клиента; общие профили Codex должны быть уже установлены
python scripts/configure_mcp.py --workspace D:\repository\1c\worktrees\smm_auto\dev1c-33021-spisanie-tmc --client all --apply
```

Для обычной ветки передай основную папку проекта.
`--output <каталог>` формирует файлы всех трёх клиентов без применения.
Без `--client` сохраняется режим Codex. `--apply-shared` управляет только Codex.
Pi и Claude Code не требуют глобальных настроек Codex.
Применение сохраняет посторонние серверы и настройки JSON.
Неизвестные составы анализаторов требуют сверки до замены.

Проектный файл pi заменяет пользовательский сервер с тем же именем целиком.
Поэтому готовый проект использует определения из этого репозитория, даже если
при миграции сохранён другой пользовательский маршрут Atlassian.

Общие определения без проектного анализатора:
[pi](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/shared/pi/mcp.json) и [Claude Code](https://github.com/highwayman2014/1c_agentic_sdlc/blob/main/mcp/configs/shared/claude/user-mcp.json).
Это четыре готовых сервиса для объединения с пользовательским `mcpServers`,
а не замена всей пользовательской конфигурации.

## Поведение и проверка

В pi выбраны `timeout=120` секунд и `exposure="codemode"`.
Инструменты доступны через встроенный codemode без загрузки всех схем в контекст модели.
Pi подключает серверы в фоне при запуске сессии. Полей адаптера `lifecycle`
и `requestTimeoutMs` в нативных файлах нет.
Broker анализатора сохраняет backend 12 часов после отключения клиентов.
Это не исправляет отказ графа или холодный старт после перезагрузки Windows.

OpenViking ограничен прежним списком инструментов через `toolExposure`.
Поиск выполняй в `viking://resources/confluence-1c/`.
Подключение не разрешает импорт материалов или операции в ИБ.

В pi проверь `/mcp` или `pi mcp list` из рабочей папки.
`pi mcp list` действительно подключает все включённые серверы:
он может запустить анализатор и его прогрев.
После изменения файлов в открытой сессии выполни `/reload`.
После отключения адаптера предпочтителен полный перезапуск pi.
Доверие к проекту определяется клиентом; эти файлы его не включают автоматически.

В Claude Code проверь `/mcp`. Для OpenViking задан явный `type="http"`.
Нативные поля pi и Codex в файл Claude Code не попадают.
После подключения проверь корни, обе wiki и готовность подсистем
по [общему списку](mcp-setup.md#проверить-подключение).

Источники: [встроенный MCP pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/mcp.md),
[настройки pi](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/settings.md),
[Claude Code MCP](https://code.claude.com/docs/en/mcp).
