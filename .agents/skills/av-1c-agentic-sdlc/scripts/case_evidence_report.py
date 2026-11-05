"""Validate screenshot evidence and build an offline 1C case report. No network/1C calls."""
from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import struct
from urllib.parse import quote

STATUSES = {'passed': 'Подтверждено', 'limited': 'Ограничение', 'not_run': 'Не проверено'}
SECRET_KEY = re.compile(r'^(password|pwd|token|secret|authorization|credentials|пароль)$', re.I)

def check_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY.fullmatch(key):
                raise ValueError('Secret-bearing field is not allowed in a report')
            check_secrets(child)
    elif isinstance(value, list):
        for child in value:
            check_secrets(child)
    elif isinstance(value, str):
        if re.search(r'(?i)/(?:P|Pwd)(?:=|\s*\")[^*\s\"]', value):
            raise ValueError('Credential command line is not allowed in a report')
        if re.search(r'(?i)https?://[^/\s]+:[^/\s]+@', value):
            raise ValueError('Credential-bearing URL is not allowed in a report')


def local_asset(root: Path, relative: str) -> Path:
    if not relative or '\\' in relative or ':' in relative or Path(relative).is_absolute():
        raise ValueError('Asset must be a relative portable path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Asset escapes the evidence directory')
    if not path.is_file():
        raise ValueError('Asset does not exist: ' + relative)
    return path


def validate(manifest: dict, root: Path) -> dict:
    check_secrets(manifest)
    if manifest.get('schema_version') != 1:
        raise ValueError('Expected schema_version=1')
    for key in ['case_id', 'title', 'verdict', 'scope', 'limitations', 'checks', 'links', 'screenshots', 'environments']:
        if key not in manifest:
            raise ValueError('Missing manifest field: ' + key)
    envs = {e['id'] for e in manifest['environments']}
    if len(envs) != len(manifest['environments']):
        raise ValueError('Duplicate environment id')
    links = {link['id']: link for link in manifest['links']}
    if len(links) != len(manifest['links']):
        raise ValueError('Duplicate navigation link id')
    for link in links.values():
        if link['environment'] not in envs:
            raise ValueError('Unknown link environment')
        nav = link['navigation_link']
        if not nav.startswith(('e1cib/data/', 'e1cib/list/')) or any(c in nav for c in ['\n', '\r', '<', '>']):
            raise ValueError('Not a 1C navigation link')
        if link.get('verified_open') is not True:
            raise ValueError('Unverified navigation link: ' + link['id'])
    if not manifest['screenshots']:
        raise ValueError('A screenshot report needs real screenshots')
    ids = set()
    for shot in manifest['screenshots']:
        if shot['id'] in ids:
            raise ValueError('Duplicate screenshot id')
        ids.add(shot['id'])
        link = links.get(shot['link_id'])
        if not link or link['environment'] != shot['environment']:
            raise ValueError('Screenshot/link environment mismatch')
        if shot.get('visual_review') != 'passed' or not shot.get('captured_at'):
            raise ValueError('Screenshot needs visual review and capture time')
        path = local_asset(root, shot['path'])
        raw = path.read_bytes()
        if raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
            raise ValueError('Screenshot must be a real PNG')
        width, height = struct.unpack('>II', raw[16:24])
        if width < 100 or height < 80:
            raise ValueError('Screenshot is too small to review')
        if hashlib.sha256(raw).hexdigest() != shot['sha256']:
            raise ValueError('Screenshot hash mismatch: ' + shot['id'])
    for check in manifest['checks']:
        if check.get('status') not in STATUSES or not check.get('evidence'):
            raise ValueError('Check needs status and evidence')
    for asset in manifest.get('data_artifacts', []):
        local_asset(root, asset['path'])
    return manifest


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def render(manifest: dict, root: Path) -> str:
    validate(manifest, root)
    limited = bool(manifest['limitations']) or any(c['status'] != 'passed' for c in manifest['checks'])
    env = {x['id']: x for x in manifest['environments']}
    links = {x['id']: x for x in manifest['links']}
    check_rows = ''.join('<tr><td>' + esc(c['title']) + '</td><td><span class="badge ' + c['status'] + '">' + STATUSES[c['status']] + '</span></td><td>' + esc(c['evidence']) + '</td></tr>' for c in manifest['checks'])
    figures = []
    for s in manifest['screenshots']:
        link = links[s['link_id']]
        facts = ''.join('<li>' + esc(t) + '</li>' for t in s['observations'])
        figures.append(f'<section class="figure" id="{esc(s["id"])}"><div class="eyebrow">{esc(env[s["environment"]]["name"])} · {esc(s["captured_at"])}</div><h2>{esc(s["title"])}</h2><ul>{facts}</ul><a href="{quote(s["path"], safe="/")}"><img src="{quote(s["path"], safe="/")}" alt="{esc(s["title"])}" loading="lazy"></a><details><summary>Источник и контроль целостности</summary><p>{esc(link["navigation_link"])}</p><code>SHA256 {esc(s["sha256"])}</code></details></section>')
    link_cards = ''.join(f'<article><strong>{esc(l["label"])}</strong><small>{esc(env[l["environment"]]["name"])}</small><code>{esc(l["navigation_link"])}</code></article>' for l in manifest['links'])
    env_rows = ''.join('<tr><td>' + esc(e['name']) + '</td><td><code>' + esc(e['ref']) + '</code></td><td>' + esc(e['connection']) + '</td><td>' + esc(e['profile']) + '</td></tr>' for e in manifest['environments'])
    limits = ''.join('<li>' + esc(s) + '</li>' for s in manifest['limitations'])
    scope = ''.join('<li>' + esc(s) + '</li>' for s in manifest['scope'])
    artifacts = ''.join(f'<li><a href="{quote(a["path"], safe="/")}">{esc(a["label"])}</a></li>' for a in manifest.get('data_artifacts', []))
    status = 'С ограничениями' if limited else 'Подтверждено'
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(manifest['case_id'])} · {esc(manifest['title'])}</title>
<style>
:root{{font-family:Segoe UI,Arial,sans-serif;color:#172b34;background:#f5f6f3;font-size:16px}}*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1180px;margin:auto;padding:48px 32px}}header{{border-top:6px solid #1a6c62;padding:28px 0 32px}}.eyebrow,small{{color:#53686d;font-size:.83rem;letter-spacing:.03em}}h1{{font-size:clamp(2rem,4vw,3.2rem);line-height:1.1;max-width:980px;margin:18px 0}}h2{{font-size:1.5rem;margin:14px 0}}p,li{{line-height:1.6}}.lead{{font-size:1.15rem;max-width:900px}}.badge{{display:inline-block;font-size:.8rem;padding:5px 10px;border-radius:4px;white-space:nowrap}}.passed{{background:#dceee7;color:#185843}}.limited{{background:#fff0ce;color:#785016}}.not_run{{background:#eceff0;color:#46585e}}section{{margin:36px 0}}.notice{{background:#fff8e9;border-left:4px solid #b87b24;padding:20px 24px}}table{{border-collapse:collapse;width:100%;font-size:.92rem}}th,td{{border-bottom:1px solid #d8dfdb;text-align:left;vertical-align:top;padding:14px 10px}}th{{color:#53686d;font-size:.8rem;text-transform:uppercase}}.figure{{background:#fff;padding:26px;border:1px solid #dce2de;border-radius:6px;break-inside:avoid}}img{{display:block;max-width:100%;height:auto;margin:22px auto 12px;border:1px solid #e0e5e1}}details{{font-size:.8rem;color:#53686d;margin-top:20px}}code{{font-family:Consolas,monospace;font-size:.82rem;overflow-wrap:anywhere}}article{{padding:16px 0;border-bottom:1px solid #d8dfdb}}article small,article code{{display:block;margin-top:8px}}a{{color:#176359}}.scroll{{overflow:auto}}footer{{border-top:1px solid #cdd7d0;margin-top:42px;padding:20px 0;font-size:.8rem;color:#53686d}}@media(max-width:650px){{main{{padding:24px 16px}}.figure{{padding:16px}}td,th{{padding:10px 6px}}}}@media print{{body{{background:white}}main{{max-width:none;padding:0}}details{{display:none}}.figure{{margin:24px 0}}a{{color:inherit}}}}
</style><main><header><div class="eyebrow">1С · ОТЧЁТ ПО КЕЙСУ · {esc(manifest['case_id'])}</div><h1>{esc(manifest['title'])}</h1><span class="badge {'limited' if limited else 'passed'}">{status}</span><p class="lead">{esc(manifest['verdict'])}</p><p class="eyebrow">Сформирован: {esc(manifest['generated_at'])}. Внутренний отчёт по dev-копиям.</p></header>
<section><h2>Границы кейса</h2><ul>{scope}</ul></section><section><h2>Результаты проверок</h2><div class="scroll"><table><thead><tr><th>Проверка</th><th>Результат</th><th>Основание</th></tr></thead><tbody>{check_rows}</tbody></table></div></section>
<section class="notice"><h2>Ограничения</h2><ul>{limits or '<li>Не зафиксированы.</li>'}</ul></section>
<section><h2>Окружение</h2><div class="scroll"><table><thead><tr><th>Копия</th><th>ИБ</th><th>BSL connection</th><th>Профиль Vanessa</th></tr></thead><tbody>{env_rows}</tbody></table></div><p>{esc(manifest.get('toolchain', ''))}</p><p>Снимки показывают состояние существующих данных на момент съёмки. Они не заменяют результаты запросов, проверки движений и контроль повторной загрузки.</p></section>
{''.join(figures)}
<section><h2>Проверенные навигационные ссылки</h2><p>Скопируйте ссылку. В указанной копии 1С откройте «Сервис и настройки → Перейти по ссылке». Ссылки e1cib не выбирают информационную базу.</p>{link_cards}</section>
<section><h2>Доказательства данных</h2><ul>{artifacts}</ul><p><a href="manifest.json">Манифест отчёта</a> · <a href="navigation-links.json">Карта навигационных ссылок</a></p></section><footer>Скриншоты получены через Vanessa Automation MCP. Изображения не дорисованы. В отчёт не включены пароли, параметры запуска с авторизацией и приватные профили.</footer></main></html>'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--check', action='store_true', help='Validate without writing HTML')
    args = p.parse_args()
    root = args.manifest.resolve().parent
    manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    validate(manifest, root)
    if not args.check:
        output = args.output or root / 'report.html'
        if output.resolve().parent != root:
            raise ValueError('HTML must stay beside the manifest so assets remain portable')
        output.write_text(render(manifest, root), encoding='utf-8')
        print(output)
    print(f'OK: {len(manifest["screenshots"])} reviewed screenshots, {len(manifest["links"])} verified links')

if __name__ == '__main__':
    main()
