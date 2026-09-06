from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_runtime.local_permission_broker import LocalPermissionBrokerClient
from agent_runtime.runtime import Runtime
from agent_runtime.toolchains.discovery import discover_toolchain
from agent_runtime.toolchains.registration import register_toolchain, prepare_toolchain, fingerprint
from agent_workbench.api.approvals import ApprovalAPI
from agent_workbench.gateways.store import GatewayProfileStore
from agent_workbench.gateways.models import MCPGatewayMember
from agent_workbench.core.config import NetworkConfig
from agent_workbench.runtime.permission_broker import DesktopPermissionBroker
from agent_workbench.servers.store import ServerProfileStore


class AutoToolchainTests(unittest.TestCase):
    def test_discovery_metadata_only_and_prefers_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve()
            binary = workspace / '.venv/bin/python'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\necho never-execute\n')
            binary.chmod(0o700)
            with patch('subprocess.run') as run:
                proposal = discover_toolchain('python', workspace)
                self.assertIsNone(discover_toolchain('unrelated-tool', workspace))
            run.assert_not_called()
            self.assertEqual(proposal['executable'], str(binary))
            self.assertEqual(proposal['read_roots'], [str(binary.parent.parent)])

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
                       'arguments': {**proposal, 'workspace': str(workspace)}}
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
                proposal = {key: self.record[key] for key in ['program', 'executable', 'read_roots']}

                def execute():
                    try:
                        if entry == 'discover':
                            report = runtime.discover_toolchains({'kinds': ['python']})
                            self.assertEqual(report['registration_errors'], {})
                            self.assertEqual(report['missing'], [])
                            self.assertFalse(report['shell_startup_files_evaluated'])
                        result.update(runtime.exec_command({'cmd': 'python -c "print(42)"'}))
                    except BaseException as exc:
                        errors.append(exc)

                if entry == 'discover':
                    runtime.toolchains._cache['python'] = {'hint': '', 'selected': None, 'candidates': []}
                try:
                    with patch.object(runtime.toolchains, 'resolve_program', return_value=None), \
                         patch('agent_runtime.toolchains.discovery.discover_toolchain', return_value=proposal):
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
