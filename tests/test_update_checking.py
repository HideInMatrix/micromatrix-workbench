from __future__ import annotations

import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent_workbench.api.update import UpdateAPI
from agent_workbench.updates.cache import CHECK_INTERVAL_SECONDS, UpdateCheckCache
from agent_workbench.updates.manager import UpdateStatus
from agent_workbench.updates.release import ReleaseInfo

RELEASE = ReleaseInfo('1.0.0', '1.1.0', 'v1.1.0', 'https://example.com/release',
                      'app', 'https://example.com/app', 'update', 'https://example.com/update',
                      'https://example.com/checksum', True)


class UpdateHarness(UpdateAPI):
    def __init__(self, path):
        self._app_version = '1.0.0'
        self._update_check_lock = threading.RLock()
        self._update_check_cache = UpdateCheckCache(path)
        self._latest_release = None
        self._append_log = Mock()
        self.manager = Mock()
        self.gateway_manager = Mock()
        self.manager.statuses.return_value = []
        self.gateway_manager.statuses.return_value = []
        self.update_manager = Mock()
        self.update_manager.status.return_value = UpdateStatus(state='ready', version='1.1.0')
        self.update_manager.install_and_restart.return_value = UpdateStatus(state='installing', version='1.1.0')
        self._window = None


class UpdateCheckingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'update-check.json'
        self.settings = {'update_download_proxy_prefix': ''}
        self.api = UpdateHarness(self.path)
        for target, values in [
            ('agent_workbench.api.update.load_settings', {'side_effect': lambda: dict(self.settings)}),
            ('agent_workbench.api.update.save_settings', {'side_effect': self.settings.update}),
            ('agent_workbench.api.update.time.time', {'return_value': 1_000_000}),
        ]:
            patcher = patch(target, **values)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def test_success_is_persisted_and_reused_after_restart_without_network(self):
        with patch('agent_workbench.api.update.fetch_latest_release', return_value=RELEASE) as fetch:
            self.api.check_update(False)
            restarted = UpdateHarness(self.path)
            cached = restarted.get_update_check_state()
            self.assertEqual(cached['release']['latest_version'], '1.1.0')
            self.assertEqual(cached['last_checked_at'], 1_000_000)
            restarted.check_update(False)
            self.assertEqual(fetch.call_count, 1)
            restarted.check_update()  # Manual requests always bypass the cache.
            self.assertEqual(fetch.call_count, 2)

    def test_expired_check_refreshes_and_failures_preserve_the_last_success(self):
        self.api._update_check_cache.write(RELEASE, '', 1_000_000 - CHECK_INTERVAL_SECONDS)
        before = self.path.read_bytes()
        with patch('agent_workbench.api.update.fetch_latest_release', side_effect=OSError('offline')):
            with self.assertRaisesRegex(OSError, 'offline'):
                self.api.check_update(False)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.api.get_update_check_state()['release']['update_available'])
        with patch('agent_workbench.api.update.fetch_latest_release', return_value=replace(RELEASE, update_available=False)) as fetch:
            result = self.api.check_update(False)
            fetch.assert_called_once()
            self.assertFalse(result['update_available'])

    def test_new_app_version_proxy_or_platform_invalidates_cache(self):
        self.api._update_check_cache.write(RELEASE, '', 1_000_000)
        self.api._app_version = '1.1.0'
        self.assertIsNone(self.api.get_update_check_state()['release'])
        self.api._app_version = '1.0.0'
        self.api.save_update_download_proxy('https://mirror.example.com')
        self.assertIsNone(self.api.get_update_check_state()['release'])
        self.settings['update_download_proxy_prefix'] = ''
        with patch('agent_workbench.updates.cache.platform_asset_name', return_value='other-platform'):
            self.assertIsNone(self.api.get_update_check_state()['release'])

    def test_corrupt_cache_and_future_timestamps_are_misses(self):
        for raw in ['broken json', '[]', '{"schema":99}']:
            self.path.write_text(raw)
            self.assertEqual(self.api.get_update_check_state(), {'release': None, 'last_checked_at': 0})
        self.api._update_check_cache.write(RELEASE, '', 1_000_001)
        self.assertIsNone(self.api.get_update_check_state()['release'])
        self.api._update_check_cache.write(RELEASE, '', 1_000_000)
        data = json.loads(self.path.read_text())
        data['release']['update_available'] = 'false'
        self.path.write_text(json.dumps(data))
        self.assertIsNone(self.api.get_update_check_state()['release'])

    def test_cache_write_failure_does_not_discard_a_successful_manual_check(self):
        with patch('agent_workbench.api.update.fetch_latest_release', return_value=RELEASE), \
             patch.object(self.api._update_check_cache, 'write', side_effect=OSError('read-only')):
            self.assertEqual(self.api.check_update()['latest_version'], '1.1.0')
        self.api._append_log.assert_called_once()

    def test_concurrent_background_checks_make_one_request(self):
        entered = threading.Event()
        finish = threading.Event()
        def fetch(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(3))
            return RELEASE
        with patch('agent_workbench.api.update.fetch_latest_release', side_effect=fetch) as request, \
             ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.api.check_update, False)
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.api.check_update, False)
            finish.set()
            self.assertEqual(first.result()['latest_version'], '1.1.0')
            self.assertEqual(second.result()['latest_version'], '1.1.0')
            request.assert_called_once()

    def test_install_preview_lists_only_running_services_and_checks_confirmed_ids(self):
        self.api.manager.statuses.return_value = [SimpleNamespace(server_id='one', name='开发环境', running=True),
                                                 SimpleNamespace(server_id='off', name='停用服务', running=False)]
        self.api.gateway_manager.statuses.return_value = [SimpleNamespace(gateway_id='one', name='Gateway', running=True)]
        impact = self.api.get_update_install_impact()
        self.assertEqual(impact, {'version': '1.1.0', 'services': [
            {'id': 'direct:one', 'name': '开发环境'}, {'id': 'gateway:one', 'name': 'Gateway'}]})
        for approved in [None, [], ['direct:one']]:
            with self.assertRaisesRegex(RuntimeError, '重新确认'):
                self.api.install_update(approved)
        self.api.update_manager.install_and_restart.assert_not_called()
        with patch('agent_workbench.api.update.threading.Thread'):
            result = self.api.install_update(['direct:one', 'gateway:one'])
        self.assertEqual(result['state'], 'installing')
        self.api.update_manager.install_and_restart.assert_called_once()

    def test_starting_a_new_service_after_preview_blocks_install(self):
        approved = [item['id'] for item in self.api.get_update_install_impact()['services']]
        self.api.manager.statuses.return_value = [SimpleNamespace(server_id='new', name='新服务', running=True)]
        with self.assertRaisesRegex(RuntimeError, '重新确认'):
            self.api.install_update(approved)
        self.api.update_manager.install_and_restart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
