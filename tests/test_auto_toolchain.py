from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_runtime.local_permission_broker import LocalPermissionBrokerClient
from agent_runtime.runtime import Runtime
from agent_runtime.toolchains.registration import register_toolchain, prepare_toolchain, fingerprint
from agent_workbench.api.approvals import ApprovalAPI
from agent_workbench.gateways.store import GatewayProfileStore
from agent_workbench.gateways.models import MCPGatewayMember
from agent_workbench.core.config import NetworkConfig
from agent_workbench.runtime.permission_broker import DesktopPermissionBroker
from agent_workbench.runtime.host_tools import resolve_host_tool
from agent_workbench.servers.store import ServerProfileStore


class AutoToolchainTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX host resolution fixture')
    def test_host_resolution_uses_login_shell_command_and_returns_only_resolved_path(self):
        completed = subprocess.CompletedProcess(
            ['shell'],
            0,
            f'noise\n__MICROMATRIX_HOST_TOOL__={sys.executable}\n',
            '',
        )
        with patch('agent_workbench.runtime.host_tools._login_shell', return_value='/bin/sh'), \
             patch('agent_workbench.runtime.host_tools.subprocess.run', return_value=completed) as run:
            result = resolve_host_tool('python3')
        self.assertEqual(result['program'], 'python3')
        self.assertEqual(result['executable'], sys.executable)
        self.assertEqual(result['resolver'], 'login_shell_command_v')
        self.assertTrue(result['shell_startup_files_evaluated'])
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], '/bin/sh')
        self.assertEqual(argv[1], '-lc')
        self.assertEqual(argv[-2], 'python3')
        self.assertNotIn('PATH', result)
        self.assertNotIn('HOME', result)

    @unittest.skipIf(os.name == 'nt', 'POSIX host resolution fixture')
    def test_host_resolution_accepts_apple_xcrun_canonical_result(self):
        completed = subprocess.CompletedProcess(
            ['shell'],
            0,
            (
                f'__MICROMATRIX_HOST_TOOL__={sys.executable}\n'
                '__MICROMATRIX_HOST_RESOLVER__=apple_xcrun\n'
            ),
            '',
        )
        with patch('agent_workbench.runtime.host_tools._login_shell', return_value='/bin/sh'), \
             patch('agent_workbench.runtime.host_tools.subprocess.run', return_value=completed):
            result = resolve_host_tool('git')
        self.assertEqual(result['executable'], sys.executable)
        self.assertEqual(result['resolver'], 'apple_xcrun')

    @unittest.skipIf(os.name == 'nt', 'POSIX host resolution fixture')
    def test_host_resolution_does_not_expose_shell_stderr(self):
        completed = subprocess.CompletedProcess(
            ['shell'],
            127,
            '',
            'TOKEN=must-not-leak',
        )
        with patch('agent_workbench.runtime.host_tools._login_shell', return_value='/bin/sh'), \
             patch('agent_workbench.runtime.host_tools.subprocess.run', return_value=completed):
            with self.assertRaises(RuntimeError) as raised:
                resolve_host_tool('missing-tool')
        self.assertNotIn('must-not-leak', str(raised.exception))

    def test_host_resolution_rejects_invalid_program_without_running_command(self):
        with patch('agent_workbench.runtime.host_tools.subprocess.run') as run:
            with self.assertRaises(ValueError):
                resolve_host_tool('../git')
        run.assert_not_called()

    def test_registration_requires_distinct_remember_decision(self):
        broker = DesktopPermissionBroker()
        try:
            client = LocalPermissionBrokerClient(broker.directory, broker.secret, 'one')
            decisions = []
            thread = threading.Thread(target=lambda: decisions.append(client.request(
                tool_name='register_toolchain', arguments={'program': 'node'},
                permission='toolchain_registration', reason='test', principal='one', timeout_seconds=5)))
            thread.start()
            pending = self.wait_pending(broker)
            for decision in [True, 'once', 'session', 'remember']:
                self.assertFalse(broker.respond(pending['request_id'], decision))
            self.assertTrue(broker.respond(pending['request_id'], 'deny'))
            thread.join(5)
            self.assertTrue(decisions[0].denied)
            self.assertIsNone(decisions[0].registration)
        finally:
            broker.cleanup()

    def test_gateway_persistence_touches_only_active_requesting_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            api = ApprovalAPI()
            api.store = ServerProfileStore(workspace / 'servers.json')
            api.gateway_store = GatewayProfileStore(workspace / 'gateways.json')
            root = MCPGatewayMember(server_id='root', name='Root', workspace=workspace,
                                    oauth_password='password', instance_path='')
            inactive = MCPGatewayMember(server_id='inactive', name='Inactive', workspace=workspace / 'missing',
                                        oauth_password='', instance_path='/inactive')
            gateway = api.gateway_store.create(name='Single', network=NetworkConfig(provider='cloudflare'),
                                               members=(root, inactive), mode='single')
            proposal = prepare_toolchain('python', sys.executable, [])
            record = {**proposal, 'version': 'test', 'runtime_target': str(Path(sys.executable).resolve()),
                      'runtime_fingerprint': fingerprint(str(Path(sys.executable).resolve()), proposal['read_roots']),
                      'fingerprint': fingerprint(proposal['executable'], proposal['read_roots'])}
            request = {'request_id': 'test', 'server_id': 'inactive', 'permission': 'toolchain_registration',
                       'arguments': {**proposal, 'workspace': str(workspace),
                                     'proposal_fingerprint': fingerprint(
                                         proposal['executable'], proposal['read_roots'])}}
            api.permission_broker = Mock()
            api.permission_broker.pending.return_value = [request]
            with patch('agent_workbench.api.approvals.register_toolchain', return_value=record) as register:
                with self.assertRaisesRegex(ValueError, '未参与运行'):
                    api.respond_permission_request('test', 'remember')
                register.assert_not_called()
                request['server_id'] = 'root'
                request['arguments']['workspace'] = str(workspace / 'other')
                with self.assertRaisesRegex(ValueError, 'Workspace'):
                    api.respond_permission_request('test', 'remember')
                register.assert_not_called()
                request['arguments']['workspace'] = str(workspace)
                api.respond_permission_request('test', 'remember')
            loaded = api.gateway_store.get(gateway.gateway_id)
            self.assertEqual(len(loaded.members[0].toolchains), 1)
            self.assertEqual(loaded.members[1], inactive)
            api.permission_broker.respond.assert_called_once_with('test', 'remember', registration=record)

    @staticmethod
    def wait_pending(broker):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pending = broker.pending()
            if pending:
                return pending[0]
            time.sleep(.02)
        raise AssertionError('No desktop consent request')


class AutoToolchainIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.record = register_toolchain('python', sys.executable, [])
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))

    def test_first_use_persists_retries_and_keeps_child_confinement(self):
        for mode, entry in [('safe', 'exec'), ('trusted', 'exec'), ('safe', 'discover')]:
            with self.subTest(mode=mode, entry=entry), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                workspace = base / 'workspace'
                workspace.mkdir()
                outside = base / 'secret'
                outside.write_text('test-secret')
                api = ApprovalAPI()
                api.store = ServerProfileStore(base / 'servers.json')
                api.gateway_store = GatewayProfileStore(base / 'gateways.json')
                profile = api.store.create(name='Test', workspace=workspace, oauth_password='test')
                other = api.store.create(name='Other', workspace=workspace, oauth_password='test')
                broker = api.permission_broker = DesktopPermissionBroker()
                client = LocalPermissionBrokerClient(broker.directory, broker.secret, profile.server_id)
                runtime = Runtime(workspace, permission_mode=mode, permission_broker=client, permission_broker_from_env=False)
                result = {}
                errors = []
                host_resolution = {
                    'program': 'python',
                    'executable': self.record['executable'],
                    'resolver': 'test-host-command',
                    'shell': '/bin/sh',
                    'shell_startup_files_evaluated': True,
                }

                def execute():
                    try:
                        if entry == 'discover':
                            report = runtime.discover_toolchains({'kinds': ['python']})
                            self.assertEqual(report['registration_errors'], {})
                            self.assertEqual(report['missing'], [])
                            self.assertTrue(report['shell_startup_files_evaluated'])
                            self.assertTrue(report['host_user_environment_queried'])
                            self.assertFalse(report['host_environment_exposed_to_ai'])
                        result.update(runtime.exec_command({'cmd': 'python -c "print(42)"'}))
                    except BaseException as exc:
                        errors.append(exc)

                if entry == 'discover':
                    runtime.toolchains._cache['python'] = {'hint': '', 'selected': None, 'candidates': []}
                try:
                    with patch.object(runtime.toolchains, 'resolve_program', return_value=None), \
                         patch('agent_workbench.runtime.permission_broker.resolve_host_tool', return_value=host_resolution):
                        thread = threading.Thread(target=execute)
                        thread.start()
                        pending = AutoToolchainTests.wait_pending(broker)
                        self.assertEqual(pending['permission'], 'toolchain_registration')
                        self.assertFalse(api.respond_permission_request(pending['request_id'], 'session'))
                        self.assertTrue(api.respond_permission_request(pending['request_id'], 'remember'))
                        thread.join(20)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(errors, errors)
                    self.assertEqual(result['stdout'], '42\n', result)
                    self.assertEqual(result['exit_code'], 0, result)
                    self.assertEqual(len(api.store.get(profile.server_id).toolchains), 1)
                    self.assertEqual(api.store.get(other.server_id).toolchains, ())
                    self.assertEqual(broker.pending(), [])
                    self.assertEqual(runtime.exec_process({'program': 'python', 'args': ['-c', 'print(43)']})['stdout'], '43\n')
                    child = f'from pathlib import Path; Path({str(outside)!r}).read_text()'
                    code = f'import subprocess,sys; sys.exit(subprocess.run([sys.executable,"-c",{child!r}]).returncode)'
                    denied = runtime.exec_process({'program': 'python', 'args': ['-c', code]})
                    self.assertNotEqual(denied['exit_code'], 0, denied)
                    self.assertIn('PermissionError', denied['stderr'])
                    target = runtime._toolchain_state_dir / 'tampered'
                    denied = runtime.exec_process({'program': 'python', 'args': ['-c', f'open({str(target)!r}, "w").write("x")']})
                    self.assertNotEqual(denied['exit_code'], 0, denied)
                finally:
                    runtime.close()
                    broker.cleanup()
