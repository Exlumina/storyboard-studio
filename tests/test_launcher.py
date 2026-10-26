"""Disposable real-launch regression tests, with no render or live-project access."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/launch_storyboard.py'


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='studio-launch-test-')
        self.root = Path(self.temp.name) / 'Project with spaces'
        self.processes = []

    def tearDown(self):
        for pid in self.processes:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.temp.cleanup()

    def run_launcher(self, *flags, root=None, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), '--project', str(root or self.root), *flags],
                                text=True, capture_output=True, timeout=20)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            if receipt.get('pid') and not receipt.get('reused'):
                self.processes.append(receipt['pid'])
            return receipt
        self.assertNotEqual(result.returncode, 0)
        return result

    def test_fresh_project_launch_resume_and_loopback(self):
        initialized = self.run_launcher('--init-only', '--title', 'Independent film')
        self.assertEqual(json.loads((self.root / 'catalog.json').read_text())['items'], [])
        self.assertEqual(json.loads((self.root / 'project.json').read_text())['target_duration_s'], None)
        receipt = self.run_launcher('--port', str(available_port()))
        self.assertTrue(receipt['url'].startswith('http://127.0.0.1:'))
        self.assertFalse(receipt['renderer_started'])
        self.assertEqual(receipt['bundle_sha256'], initialized['bundle_sha256'])
        with urllib.request.urlopen(receipt['url'] + 'api/project') as response:
            self.assertEqual(json.load(response)['title'], 'Independent film')
        reused = self.run_launcher('--port', str(available_port()))
        self.assertTrue(reused['reused'])
        self.assertEqual(reused['pid'], receipt['pid'])

    def test_live_refresh_and_changed_python_are_rejected_before_writes(self):
        self.run_launcher('--port', str(available_port()))
        before = (self.root / 'project.json').read_bytes()
        failure = self.run_launcher('--refresh-ui', '--approved-model-version', 'new-model', success=False)
        self.assertIn('Studio is running', failure.stderr)
        self.assertEqual((self.root / 'project.json').read_bytes(), before)
        self.assertFalse((self.root / 'data/ui-backups').exists())
        with (self.root / 'server.py').open('a') as output:
            output.write('\n# changed on disk\n')
        failure = self.run_launcher(success=False)
        self.assertIn('code changed', failure.stderr)

    def test_stopped_refresh_preserves_board_catalog_and_backup(self):
        self.run_launcher('--init-only')
        board = (self.root / 'data/board.json').read_bytes()
        catalog = (self.root / 'catalog.json').read_bytes()
        (self.root / 'app.js').write_text('// custom old UI\n')
        receipt = self.run_launcher('--init-only', '--refresh-ui')
        self.assertEqual((self.root / 'data/board.json').read_bytes(), board)
        self.assertEqual((self.root / 'catalog.json').read_bytes(), catalog)
        backups = list((self.root / 'data/ui-backups').glob('*/app.js'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '// custom old UI\n')
        self.assertEqual(receipt['files_sha256']['app.js'], hashlib.sha256((self.root / 'app.js').read_bytes()).hexdigest())

    def test_cloned_project_identity_does_not_reuse_another_root(self):
        first = self.run_launcher('--port', str(available_port()))
        other = Path(self.temp.name) / 'Clone'
        self.run_launcher('--init-only', root=other)
        (other / 'project.json').write_bytes((self.root / 'project.json').read_bytes())
        second = self.run_launcher('--port', first['url'].split(':')[-1].rstrip('/'), root=other)
        self.assertNotEqual(second['pid'], first['pid'])
        self.assertNotEqual(second['url'], first['url'])
        self.assertEqual(second['project'], str(other.resolve()))

    def test_symlink_and_invalid_config_rejected_without_copying(self):
        self.root.mkdir()
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('preserve')
        (self.root / 'app.js').symlink_to(outside)
        self.run_launcher('--init-only', '--refresh-ui', success=False)
        self.assertEqual(outside.read_text(), 'preserve')
        self.assertFalse((self.root / 'server.py').exists())
        other = Path(self.temp.name) / 'Malformed'
        other.mkdir()
        (other / 'project.json').write_text('[]')
        self.run_launcher('--init-only', root=other, success=False)
        self.assertFalse((other / 'server.py').exists())

    def test_custom_bundle_and_stale_pid_receipt_are_explicit(self):
        self.run_launcher('--init-only')
        with (self.root / 'app.js').open('a') as output:
            output.write('\n// custom project UI\n')
        receipt = self.run_launcher('--port', str(available_port()))
        self.assertEqual(receipt['bundle_version'], 'custom')
        launch = self.root / 'data/launch.json'
        saved = json.loads(launch.read_text())
        saved['command'][3] = '/some/other/project'
        launch.write_text(json.dumps(saved))
        result = self.run_launcher(success=False)
        self.assertIn('PID/command cannot be verified', result.stderr)

    def test_running_process_with_invalid_url_still_blocks_refresh(self):
        self.run_launcher('--port', str(available_port()))
        launch = self.root / 'data/launch.json'
        saved = json.loads(launch.read_text())
        saved['url'] = 'https://example.com/'
        launch.write_text(json.dumps(saved))
        result = self.run_launcher('--refresh-ui', success=False)
        self.assertIn('Studio is running', result.stderr)
        self.assertFalse((self.root / 'data/ui-backups').exists())

    def test_occupied_alias_leaves_listener_untouched(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            alias = listener.getsockname()[1]
            result = self.run_launcher('--alias-port', str(alias), '--port', str(available_port()), success=False)
            self.assertIn('occupied', result.stderr)
            self.assertEqual(listener.getsockname()[1], alias)
            self.assertFalse((self.root / 'data/launch.json').exists())

    def test_receipt_queries_reject_external_urls_and_redirects(self):
        spec = importlib.util.spec_from_file_location('launcher', SCRIPT)
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        self.assertIsNone(launcher.query_project('https://example.com/'))
        self.assertIsNone(launcher.query_project('http://127.0.0.1:99999/'))
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', 'https://example.com/')
                self.end_headers()
            def log_message(self, *args):
                pass
        with HTTPServer(('127.0.0.1', 0), Redirect) as service:
            worker = threading.Thread(target=service.serve_forever)
            worker.start()
            try:
                self.assertIsNone(launcher.query_project(f'http://127.0.0.1:{service.server_port}/'))
            finally:
                service.shutdown()
                worker.join()

    def test_invalid_input_does_not_initialize(self):
        for flags in [('--duration', 'nan'), ('--duration', '-1'), ('--port', '65536')]:
            self.run_launcher(*flags, success=False)
            self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
