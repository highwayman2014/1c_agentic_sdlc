"""Check a real BSL workspace, not merely generated config. No live 1C calls.

Exit 0: requested capabilities verified; 2: warming/degraded; 1: failure.
A semantic query is sent ONLY when --query is explicit. Provider access remains
subject to the existing exact-source launch policy. Never restart or rebuild.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import tempfile
import time
import tomllib
from atomic_files import atomic_text

REPOSITORY = Path(__file__).resolve().parent.parent
REQUIRED = {'search', 'syntax_help', 'outline', 'symbol_info', 'references', 'graph', 'metadata', 'diagnostics'}


def redact(text):
    text = re.sub(r'(?i)(postgres(?:ql)?://)[^/\s:@]+:[^@\s]+@', r'\1<REDACTED>@', text)
    return re.sub(r'(?i)(bearer\s+|(?:password|api[_-]?key|token)\s*[=:]\s*)([^\s,;"}]+)', r'\1<REDACTED>', text)


class Mcp:
    def __init__(self, command, root, env=None, timeout=120):
        self.timeout, self.serial = timeout, 0
        self.messages, self.errors = queue.Queue(), []
        self.process = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try: self.messages.put(json.loads(line))
                except json.JSONDecodeError: pass
        finally: self.messages.put(None)

    def _stderr(self):
        for line in self.process.stderr:
            self.errors.append(redact(line.rstrip()))
            self.errors[:] = self.errors[-20:]

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.serial += 1
        self.send({'jsonrpc': '2.0', 'id': self.serial, 'method': method, 'params': params})
        end = time.monotonic() + self.timeout
        while True:
            try: value = self.messages.get(timeout=max(.01, end-time.monotonic()))
            except queue.Empty: raise RuntimeError(f'MCP {method} timed out; no restart attempted')
            if value is None:
                raise RuntimeError(f'MCP closed during {method}; stderr: ' + ' | '.join(self.errors))
            if value.get('id') == self.serial:
                if 'error' in value: raise RuntimeError(redact(json.dumps(value['error'], ensure_ascii=False)))
                return value['result']

    def initialize(self):
        r = self.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'sdlc-workspace-health', 'version': '1.0'}})
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return r.get('serverInfo', {})

    def call(self, name, arguments):
        r = self.request('tools/call', {'name': name, 'arguments': arguments})
        if r.get('isError'): raise RuntimeError(redact(json.dumps(r, ensure_ascii=False)))
        return r

    def close(self):
        try:
            if not self.process.stdin.closed: self.process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try: self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            # Own disposable wrapper only, never taskkill /T or a shared daemon.
            self.process.terminate()
            self.process.wait(timeout=8)


def payload(response):
    if 'structuredContent' in response: return response['structuredContent']
    for item in response.get('content', []):
        if item.get('type') == 'text':
            try: return json.loads(item['text'])
            except json.JSONDecodeError: pass
    return {}


def readiness(response, kind):
    value = payload(response)
    for target in value.get('indexing', {}).get('targets', []):
        if target.get('kind') == kind: return target.get('state', 'unknown')
    if kind == 'semantic': return 'unknown'
    return value.get('state', 'unknown')


def assess(statuses, semantic=False):
    states = {name: readiness(value, 'lexical' if name == 'search' else name)
              for name, value in statuses.items()}
    if semantic:
        search = payload(statuses['search'])
        states['semantic'] = readiness(statuses['search'], 'semantic')
        targets = search.get('indexing', {}).get('targets', [])
        lexical = next((t for t in targets if t.get('kind') == 'lexical'), {})
        sem = next((t for t in targets if t.get('kind') == 'semantic'), {})
        # 0.4.3 reports native_failure before it has published any engine. Preserve
        # raw evidence, but treat this exact initializing contradiction as waiting.
        if (search.get('state') == 'loading' and lexical.get('reason_code') == 'initializing'
                and sem.get('reason_code') == 'native_failure' and sem.get('pass_id') is None):
            states['semantic'] = 'waiting'
    if any(s in ('failed', 'error') for s in states.values()): return 1, states
    return (0 if all(s == 'ready' for s in states.values()) else 2), states


def semantic_verified(response):
    value = payload(response)
    modalities = [h.get('modality') for h in value.get('hits', [])]
    complete = value.get('freshness', {}).get('completeness', {}).get('status')
    return any(m in ('S', 'L+S') for m in modalities) and complete == 'complete'


def demand_probe_admissible(statuses):
    if any(readiness(statuses[name], name) != 'ready' for name in ('graph', 'metadata', 'diagnostics')):
        return False
    search = payload(statuses['search'])
    if search.get('state') != 'ready': return False
    targets = {t.get('kind'): t for t in search.get('indexing', {}).get('targets', [])}
    for kind in ('lexical', 'semantic'):
        target = targets.get(kind, {})
        if target.get('state') == 'ready': continue
        if not (target.get('state') == 'unknown' and target.get('reason_code') == 'snapshot_unavailable' and target.get('phase') is None):
            return False
    return True


def check_layout(workspace):
    path = workspace / 'bsl-analyzer.toml'
    config = tomllib.loads(path.read_text(encoding='utf-8-sig'))
    source = config.get('source', {})
    roots = [('configuration', source.get('root', 'src/cf'))]
    for item in source.get('extensions', []):
        roots.append((item.get('name', '') if isinstance(item, dict) else '',
                      item['path'] if isinstance(item, dict) else item))
    resolved = []
    for name, relative in roots:
        matches = list(workspace.glob(relative))
        if not matches or any(not p.is_dir() for p in matches):
            raise ValueError('Configured source root missing: ' + relative)
        if name == 'configuration' and not (matches[0] / 'Configuration.xml').is_file():
            raise ValueError('Configuration.xml missing in configured root')
        resolved.extend({'name': name, 'path': str(p.resolve())} for p in matches)
    return config.get('search', {}).get('baseline', {}).get('backend', 'sqlite'), resolved


def live_progress_path(workspace, requested, wait_seconds):
    if requested is None or wait_seconds <= 0:
        return None
    requested = Path(requested).resolve()
    if requested.is_relative_to(Path(workspace).resolve()):
        # Keep repeated atomic replacements away from the source tree watcher.
        return Path(tempfile.mkdtemp(prefix='sdlc-workspace-health-')) / 'health.json'
    return requested


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', type=Path, required=True)
    ap.add_argument('--wait', type=int, default=0)
    ap.add_argument('--lexical-only', action='store_true')
    ap.add_argument('--require-semantic', action='store_true')
    ap.add_argument('--require-shared-baseline', action='store_true')
    ap.add_argument('--query', help='Explicitly authorize one semantic smoke query; provider policy still applies')
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    if a.lexical_only and (a.require_semantic or a.query): ap.error('lexical-only conflicts with semantic checks')
    root = a.workspace.resolve()
    report = {'workspace': str(root), 'history': []}
    progress = live_progress_path(root, a.output, a.wait)
    if progress is not None:
        report['live_progress_path'] = str(progress)
        print(json.dumps({'live_progress_path': str(progress)}), flush=True)
    client = None
    try:
        backend, roots = check_layout(root)
        report.update(backend=backend, roots=roots, shared_baseline_configured=(backend == 'postgres'))
        if a.require_shared_baseline and backend != 'postgres':
            raise ValueError('SQLiteLocal is not proof of an external shared baseline; no MCP started')
        env = dict(os.environ); env['CLAUDE_PROJECT_DIR'] = str(root)
        command = [sys.executable, str(REPOSITORY/'scripts/mcp_profile.py'), 'bsl-unified']
        if a.lexical_only: command.append('--lexical-only')
        client = Mcp(command, root, env)
        report['server'] = client.initialize()
        tools = client.request('tools/list', {})
        report['tools'] = [t['name'] for t in tools['tools']]
        if not REQUIRED <= set(report['tools']): raise ValueError('Workspace toolkit incomplete')
        end = time.monotonic() + a.wait
        while True:
            statuses = {}
            for name in ('search', 'graph', 'metadata', 'diagnostics'):
                args = {'action': 'status'}
                if name == 'metadata': args['mode'] = 'source'
                statuses[name] = client.call(name, args)
            code, states = assess(statuses, a.require_semantic or bool(a.query))
            report['history'].append({'time': time.time(), 'states': states, 'responses': statuses})
            if progress is not None:
                atomic_text(progress, redact(json.dumps(report, ensure_ascii=False, indent=2)))
            print(json.dumps({'states': states, 'indexing': payload(statuses['search']).get('indexing')}, ensure_ascii=False), flush=True)
            search_text = '\n'.join(c.get('text', '') for c in statuses['search'].get('content', []))
            roots_confirmed = all(r['path'].replace('/', '\\').lower() in search_text.replace('/', '\\').lower() for r in roots)
            if code == 0 or (a.query and demand_probe_admissible(statuses)):
                if not roots_confirmed:
                    code = 2; report['root_verification'] = 'configured roots not yet confirmed by search status'
                else: report['root_verification'] = 'confirmed by actual search status'
            demand_probe = bool(a.query) and roots_confirmed and demand_probe_admissible(statuses)
            if code != 2 or demand_probe or time.monotonic() >= end: break
            time.sleep(min(30, max(0, end-time.monotonic())))
        if (code == 0 or demand_probe) and a.query:
            r = client.call('search', {'action': 'search_code', 'query': a.query, 'limit': 5, 'max_output_tokens': 3500})
            report['semantic_query'] = r
            report['modalities'] = [h.get('modality') for h in payload(r).get('hits', [])]
            code = 0 if semantic_verified(r) else 2
            report['query_status_after'] = client.call('search', {'action': 'status'})
        report['exit_code'] = code
        return code
    except Exception as error:
        report['error'] = redact(str(error)); report['exit_code'] = 1
        print(report['error'], file=sys.stderr)
        return 1
    finally:
        if client: client.close()
        if a.output:
            a.output.parent.mkdir(parents=True, exist_ok=True)
            atomic_text(a.output, redact(json.dumps(report, ensure_ascii=False, indent=2)))


if __name__ == '__main__': sys.exit(main())
