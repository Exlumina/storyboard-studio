"""Initialize or resume an isolated loopback Storyboard Studio; never render."""
import argparse
import hashlib
import json
import math
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BUNDLE_VERSION = '0.5.2'
UI_FILES = ('index.html', 'app.js', 'styles.css', 'server.py', 'feedback_handoff.py',
            'render_return.py', 'render_handoff.py', 'storyboard_reader.py', 'storyboard_conformance.py')


def read_object(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise SystemExit(f'Cannot read {path}: {error}. Existing files are preserved.')
    if not isinstance(value, dict):
        raise SystemExit(f'{path} must contain a JSON object. Existing files are preserved.')
    return value


def file_receipt(root):
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in UI_FILES}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    template = Path(__file__).resolve().parents[1] / 'assets' / 'storyboard-studio'
    canonical = all(hashlib.sha256((template / name).read_bytes()).hexdigest() == value for name, value in hashes.items())
    return {'launcher_version': BUNDLE_VERSION, 'bundle_version': BUNDLE_VERSION if canonical else 'custom',
            'bundle_sha256': digest, 'files_sha256': hashes}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def query_project(url):
    # Receipts may be user-edited: never make a request outside loopback.
    if not re.fullmatch(r'http://127\.0\.0\.1:([0-9]+)/', url):
        return None
    port = int(url.split(':')[-1].rstrip('/'))
    if not 1 <= port <= 65535:
        return None
    try:
        with urllib.request.build_opener(NoRedirect).open(url + 'api/project', timeout=.5) as response:
            value = json.load(response)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def owned_process(receipt, root):
    command = receipt.get('command')
    pid = receipt.get('pid')
    if receipt.get('project') != str(root) or not isinstance(command, list) or not isinstance(pid, int) or pid <= 0:
        return False
    if len(command) < 6 or command[1:4] != [str(root / 'server.py'), '--project', str(root)]:
        return False
    try:
        actual = subprocess.check_output(['ps', '-ww', '-p', str(pid), '-o', 'command='], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    expected = {' '.join(command)}
    # macOS framework Python replaces its launcher executable after startup.
    framework_app = Path(command[0]).resolve().parent.parent / 'Resources/Python.app/Contents/MacOS/Python'
    if framework_app.is_file():
        expected.add(' '.join([str(framework_app), *command[1:]]))
    return actual in expected


def free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--title', default='Storyboard project')
    ap.add_argument('--duration', type=float)
    ap.add_argument('--port', type=int, default=8840)
    ap.add_argument('--init-only', action='store_true')
    ap.add_argument('--alias-port', type=int, action='append', default=[])
    ap.add_argument('--chat-thread-id')
    ap.add_argument('--refresh-ui', action='store_true')
    ap.add_argument('--approved-model-version')
    args = ap.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit('Run this helper with Python 3.11 or newer.')
    if any(not 1 <= port <= 65535 for port in [args.port, *args.alias_port]):
        ap.error('Ports must be between 1 and 65535.')
    if len(set(args.alias_port)) != len(args.alias_port):
        ap.error('Alias ports must be distinct.')
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        ap.error('Duration must be a finite positive number.')
    root = args.project.expanduser().resolve()
    template = Path(__file__).resolve().parents[1] / 'assets' / 'storyboard-studio'
    # Validate all mutable targets before copying any code or creating defaults.
    for name in (*UI_FILES, 'project.json', 'catalog.json', 'data', 'assets',
                 'data/board.json', 'data/launch.json', 'data/server.log',
                 'data/ui-backups', 'data/project-backups', 'data/bundle.json'):
        path = root / name
        if path.is_symlink():
            raise SystemExit(f'Refusing symbolic-link target: {path}. Existing files are preserved.')
        if path.exists() and path.is_dir() != (name in ('data', 'assets', 'data/ui-backups', 'data/project-backups')):
            raise SystemExit(f'Unexpected target type: {path}. Existing files are preserved.')
    for name in UI_FILES:
        if not (template / name).is_file():
            raise SystemExit(f'Bundle is incomplete: {name}. Existing files are preserved.')
    config = read_object(root / 'project.json') if (root / 'project.json').exists() else None
    if config is not None and (not isinstance(config.get('id'), str) or not config['id'].strip()):
        raise SystemExit('Existing project.json needs a nonempty project ID. Existing files are preserved.')
    for name in ('catalog.json', 'data/board.json'):
        if (root / name).exists():
            read_object(root / name)
    previous = read_object(root / 'data/launch.json') if (root / 'data/launch.json').exists() else {}
    active = query_project(previous.get('url', ''))
    matching = bool(config and active and active.get('id') == config['id'])
    owned_running = owned_process(previous, root)
    if (matching or owned_running) and args.refresh_ui:
        raise SystemExit('Studio is running. Stop its verified project-owned server before --refresh-ui, then launch again. No files were changed.')
    if owned_running and not matching:
        raise SystemExit('The project-owned server is running but its loopback identity is unavailable. Verify and stop it before relaunching. No files were changed.')
    if matching:
        if not owned_running:
            raise SystemExit('A matching service exists, but its project-owned PID/command cannot be verified. Verify and stop it before relaunching. No files were changed.')
        if any(not (root / name).is_file() for name in UI_FILES) or previous.get('files_sha256') != file_receipt(root)['files_sha256']:
            raise SystemExit('Project code changed while Studio is running. Stop the verified server and relaunch to load it. No files were changed.')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'assets').mkdir(exist_ok=True)
    (root / 'data').mkdir(exist_ok=True)
    backup = None
    for name in UI_FILES:
        destination = root / name
        if not destination.exists() or args.refresh_ui:
            if destination.exists():
                if backup is None:
                    backup = root / 'data/ui-backups' / str(time.time_ns())
                    backup.mkdir(parents=True)
                shutil.copy2(destination, backup / name)
            shutil.copy2(template / name, destination)
    defaults = {
        'project.json': {'id': uuid.uuid4().hex, 'title': args.title, 'target_duration_s': args.duration,
                         'asset_policy': 'latest-approved', 'reference_policy': 'visual-reference-only',
                         'marker_supported': True, 'approved_model_version': args.approved_model_version},
        'catalog.json': {'schema_version': 1, 'items': []},
        'data/board.json': {'schema_version': 1, 'title': args.title, 'asset_policy': 'latest-approved',
                            'target_duration_s': args.duration, 'nodes': [], 'edges': [],
                            'chosen_path': [], 'render_path_ends_here': True}}
    for name, value in defaults.items():
        destination = root / name
        if not destination.exists():
            destination.write_text(json.dumps(value, indent=2) + '\n')
    config = read_object(root / 'project.json')
    changed = False
    for key, value in (('approved_model_version', args.approved_model_version), ('chat_thread_id', args.chat_thread_id)):
        if value and config.get(key) != value:
            if not changed:
                backup = root / 'data/project-backups' / str(time.time_ns())
                backup.mkdir(parents=True)
                shutil.copy2(root / 'project.json', backup / 'project.json')
            config[key] = value
            changed = True
    if changed:
        (root / 'project.json').write_text(json.dumps(config, indent=2) + '\n')
    bundle = file_receipt(root)
    (root / 'data/bundle.json').write_text(json.dumps(bundle, indent=2) + '\n')
    if args.init_only:
        print(json.dumps({'project': str(root), 'initialized': True, **bundle}))
        return
    if matching:
        print(json.dumps({**previous, 'reused': True}))
        return
    for alias in args.alias_port:
        if not free_port(alias):
            raise SystemExit(f'Alias port {alias} is occupied. Existing service was left untouched.')
    for port in range(args.port, min(args.port + 20, 65536)):
        if port in args.alias_port or not free_port(port):
            continue
        url = f'http://127.0.0.1:{port}/'
        command = [sys.executable, str(root / 'server.py'), '--project', str(root), '--port', str(port)]
        for alias in args.alias_port:
            command += ['--alias-port', str(alias)]
        with (root / 'data/server.log').open('ab') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        for _ in range(30):
            if process.poll() is not None:
                break
            result = query_project(url)
            if result and result.get('id') == config['id'] and owned_process({'project': str(root), 'pid': process.pid, 'command': command}, root):
                receipt = {'project': str(root), 'url': url, 'pid': process.pid, 'command': command,
                           'renderer_started': False, 'version': bundle['bundle_version'], **bundle}
                (root / 'data/launch.json').write_text(json.dumps(receipt, indent=2) + '\n')
                print(json.dumps(receipt))
                return
            time.sleep(.1)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise SystemExit('Local server did not start. Inspect data/server.log; project files are preserved.')
    raise SystemExit('No free loopback port found; project files are preserved.')


if __name__ == '__main__':
    main()
