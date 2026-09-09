from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_runtime.errors import ToolError
from agent_runtime.runtime import Runtime
from agent_runtime.permissions.context import ACTIVE_PERMISSIONS
from agent_runtime.sandbox.backend import (
    ProcessSandboxBackend,
    SandboxBackendState,
    create_process_sandbox,
)
from agent_runtime.toolchains.registration import (
    fingerprint, normalize_registrations, prepare_toolchain,
    register_toolchain, require_confinement,
)
from agent_runtime.tools.process.policy import ProcessCommandPolicy
from agent_workbench.core.config import NetworkConfig
from agent_workbench.gateways.models import MCPGatewayMember, MCPGatewayProfile
from agent_workbench.servers.models import MCPServerProfile
from agent_workbench.servers.store import ServerProfileStore


class ToolchainRegistrationTests(unittest.TestCase):
    def test_inspection_never_executes_program_or_login_shell(self):
        with patch('subprocess.run') as run:
            proposal = prepare_toolchain('python', sys.executable, [])
        run.assert_not_called()
        self.assertEqual(proposal['executable'], sys.executable)
        self.assertNotIn(str(Path.home()), proposal['read_roots'])

    def test_registration_freezes_identity_without_executing_program(self):
        with patch('subprocess.Popen') as popen, patch('subprocess.run') as run:
            record = register_toolchain('python', sys.executable, [])
        popen.assert_not_called()
        run.assert_not_called()
        self.assertEqual(record['version'], '')
        self.assertEqual(record['runtime_target'], '')
        self.assertRegex(record['fingerprint'], r'^[0-9a-f]{64}$')
        self.assertEqual(normalize_registrations([record])[0], record)

    def test_home_and_credentials_cannot_be_registered(self):
        for root in [str(Path.home()), '/', str(Path.home() / '.ssh')]:
            with self.subTest(root=root), self.assertRaises(ValueError):
                prepare_toolchain('python', sys.executable, [root])

    def test_confirmed_read_scope_cannot_silently_expand(self):
        with patch('subprocess.run') as run, self.assertRaisesRegex(ValueError, '重新检查'):
            register_toolchain('python', sys.executable, [], confirmed_roots=[])
        run.assert_not_called()

    def test_require_rejects_disabled_and_partial_sandbox(self):
        for enabled in [False, True]:
            backend = ProcessSandboxBackend(SandboxBackendState(
                name='test', available=True, enabled=enabled, reason='no filesystem boundary',
                process_isolation=enabled,
            ))
            with self.assertRaisesRegex(RuntimeError, '完整 OS'):
                require_confinement(backend)

    def test_inline_scripts_are_allowed_only_with_kernel_confinement(self):
        for confined in [False, True]:
            policy = ProcessCommandPolicy(
                permission_mode='safe', kernel_confined=confined, allow_network=False,
                permission_granted=lambda _: False, validate_writable_path=lambda _: None,
            )
            if confined:
                policy.validate('python -c "print(42)"', {}, 1000)
            else:
                with self.assertRaises(ToolError):
                    policy.validate('python -c "print(42)"', {}, 1000)

    def test_registration_survives_direct_and_gateway_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = prepare_toolchain('python', sys.executable, [])
            record = {**proposal, 'version': 'test-version',
                      'runtime_target': str(Path(sys.executable).resolve()),
                      'runtime_fingerprint': fingerprint(str(Path(sys.executable).resolve()), proposal['read_roots']),
                      'fingerprint': fingerprint(proposal['executable'], proposal['read_roots'])}
            records = normalize_registrations([record])
            store = ServerProfileStore(root / 'servers.json')
            server = store.create(name='Test', workspace=root, oauth_password='password',
                                  network=NetworkConfig(provider='cloudflare'), toolchains=records)
            loaded = store.get(server.server_id)
            self.assertEqual(loaded.toolchains, records)
            self.assertEqual(loaded.to_launch_config().toolchains, records)
            member = MCPGatewayMember(server_id='root', name='Root', workspace=root,
                                      oauth_password='password', instance_path='', toolchains=records)
            gateway = MCPGatewayProfile.create(name='Test', network=server.network,
                                               members=(member,), mode='single')
            loaded_gateway = MCPGatewayProfile.from_dict(gateway.to_dict())
            self.assertEqual(loaded_gateway.runtime_launch_config().profiles[0].toolchains, records)
            self.assertEqual(replace(loaded_gateway, mode='multi').to_launch_config().profiles[0].toolchains, records)

    def test_changed_binary_is_rejected_before_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'python'
            binary.write_text('#!/bin/sh\necho first\n')
            binary.chmod(0o700)
            record = {'program': 'python', 'executable': str(binary), 'read_roots': [str(root.resolve())],
                      'version': 'first', 'runtime_target': str(binary),
                      'runtime_fingerprint': fingerprint(str(binary), [str(root.resolve())]), 'fingerprint': fingerprint(str(binary), [str(root.resolve())])}
            binary.write_text('#!/bin/sh\necho changed\n')
            with patch('subprocess.run') as run, self.assertRaisesRegex(ToolError, '重新确认'):
                Runtime(root, toolchains=[record])
            run.assert_not_called()

    def test_stale_registration_remains_loadable_for_desktop_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'npm'
            binary.write_text('#!/bin/sh\necho 1\n')
            binary.chmod(0o700)
            roots = [str(root.resolve())]
            record = {'program': 'npm', 'executable': str(binary), 'read_roots': roots,
                      'version': '1', 'fingerprint': fingerprint(str(binary), roots)}
            store = ServerProfileStore(root / 'servers.json')
            profile = store.create(name='Test', workspace=root, oauth_password='password',
                                   toolchains=normalize_registrations([record]))
            binary.unlink()
            loaded = store.get(profile.server_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.toolchains[0]['executable'], str(binary))
            with self.assertRaises(ToolError):
                Runtime(root, toolchains=loaded.toolchains)



class ToolchainConfinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        try:
            backend = create_process_sandbox(
                mode='safe', workspace=root, runtime_dir=root,
                readable_roots=[], writable_roots=[root], protected_paths=[],
                network=False,
            )
            require_confinement(backend)
            cls.record = register_toolchain('python', sys.executable, [])
        except RuntimeError as exc:
            raise unittest.SkipTest(f'OS confinement unavailable: {exc}')

    def test_safe_and_trusted_execute_without_login_environment_approval(self):
        for mode in ['safe', 'trusted']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                runtime = Runtime(Path(temporary), permission_mode=mode,
                                  toolchains=[self.record], permission_broker_from_env=False)
                try:
                    result = runtime.exec_process({'program': 'python', 'args': ['-c', 'print(42)']})
                    self.assertEqual(result['exit_code'], 0, result)
                    self.assertEqual(result['stdout'], '42\n')
                    absolute = runtime.exec_process({'program': self.record['executable'], 'args': ['--version']})
                    self.assertEqual(absolute['exit_code'], 0, absolute)
                    shell = runtime.exec_command({'cmd': 'python -c "print(43)"'})
                    self.assertEqual(shell['exit_code'], 0, shell)
                    self.assertEqual(shell['stdout'], '43\n')
                finally:
                    runtime.close()

    def test_package_manager_registration_survives_mode_switch_and_hot_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            workspace = base / 'workspace'
            workspace.mkdir()
            binary = base / 'tools' / 'pnpm'
            binary.parent.mkdir()
            # Model a manager shim that provisions a project's requested pnpm
            # before delegating to pnpm (and ignores pnpm's environment flags).
            binary.write_text(
                '#!/bin/sh\n'
                'if [ -f package.json ]; then\n'
                ' echo "project version switch attempted" >&2; exit 42\n'
                'fi\n'
                'echo 11.22.0\n'
            )
            binary.chmod(0o700)
            (workspace / 'package.json').write_text('{"packageManager":"pnpm@11.25.0"}')
            record = register_toolchain('pnpm', str(binary), [])
            for mode in ['dangerous', 'safe', 'trusted']:
                with self.subTest(mode=mode):
                    runtime = Runtime(workspace, permission_mode=mode, toolchains=[record],
                                      permission_broker_from_env=False)
                    try:
                        runtime._verify_registered_toolchains()
                        runtime._install_registered_toolchain(record)
                        self.assertEqual(runtime.toolchain_registrations[0]['version'], '')
                        result = runtime.exec_process({'program': 'pnpm', 'args': ['--version']})
                        self.assertEqual(result['exit_code'], 42, result)
                        self.assertIn('project version switch attempted', result['stderr'])
                    finally:
                        runtime.close()

    def test_child_process_cannot_read_external_secret_or_write_outside(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / 'workspace'
            workspace.mkdir()
            secret = base / 'private-test-key'
            secret.write_text('test-only-secret')
            outside = base / 'outside-write'
            child = (
                'from pathlib import Path\n'
                f'for path, write in [(Path({str(secret)!r}), False), (Path({str(outside)!r}), True)]:\n'
                ' try:\n'
                '  path.write_text("escaped") if write else path.read_text()\n'
                '  print("ESCAPED")\n'
                ' except PermissionError:\n'
                '  print("blocked")\n'
            )
            (workspace / 'check.py').write_text(
                'import subprocess, sys, os\n'
                'from pathlib import Path\n'
                f'subprocess.run([sys.executable, "-c", {child!r}], check=True)\n'
                'cache = Path(os.environ["PIP_CACHE_DIR"])\n'
                'cache.mkdir(parents=True, exist_ok=True)\n'
                '(cache / "ok").write_text("cached")\n'
                'print("cache-ok")\n'
            )
            runtime = Runtime(workspace, toolchains=[self.record], permission_broker_from_env=False)
            try:
                for grants in [frozenset(), frozenset({'network', 'git_metadata_write'})]:
                    token = ACTIVE_PERMISSIONS.set(grants)
                    try:
                        result = runtime.exec_process({'program': 'python', 'args': ['check.py']})
                    finally:
                        ACTIVE_PERMISSIONS.reset(token)
                    self.assertEqual(result['exit_code'], 0, result)
                    self.assertEqual(result['stdout'], 'blocked\nblocked\ncache-ok\n')
                self.assertFalse(outside.exists())
            finally:
                runtime.close()

    def test_safe_network_and_policy_file_tampering_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            runtime = Runtime(workspace, toolchains=[self.record], permission_broker_from_env=False)
            try:
                (workspace / 'network.py').write_text(
                    'import socket\n'
                    'try:\n'
                    ' s=socket.socket(); s.settimeout(1); s.connect(("127.0.0.1", 9))\n'
                    'except PermissionError:\n'
                    ' print("blocked")\n'
                )
                result = runtime.exec_process({'program': 'python', 'args': ['network.py']})
                self.assertEqual(result['stdout'], 'blocked\n', result)
                if sys.platform == 'darwin':
                    path = runtime.process_sandbox.profile_path
                    original = path.read_text()
                    (workspace / 'tamper.py').write_text(
                        'from pathlib import Path\n'
                        f'try: Path({str(path)!r}).write_text("(allow default)")\n'
                        'except PermissionError: print("blocked")\n'
                    )
                    result = runtime.exec_process({'program': 'python', 'args': ['tamper.py']})
                    self.assertEqual(result['stdout'], 'blocked\n', result)
                    self.assertEqual(path.read_text(), original)
            finally:
                runtime.close()

    def test_dependency_directory_stays_read_only_after_git_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            libraries = workspace / 'registered-libraries'
            libraries.mkdir()
            record = register_toolchain('python', sys.executable, [str(libraries)])
            runtime = Runtime(workspace, toolchains=[record], permission_broker_from_env=False)
            try:
                with self.assertRaisesRegex(ToolError, '只读'):
                    runtime.workspace.writable('registered-libraries/file')
                (workspace / 'check.py').write_text(
                    'from pathlib import Path\n'
                    'try: Path("registered-libraries/file").write_text("changed")\n'
                    'except PermissionError: print("blocked")\n'
                )
                token = ACTIVE_PERMISSIONS.set(frozenset({'git_metadata_write'}))
                try:
                    result = runtime.exec_process({'program': 'python', 'args': ['check.py']})
                finally:
                    ACTIVE_PERMISSIONS.reset(token)
                self.assertEqual(result['stdout'], 'blocked\n', result)
            finally:
                runtime.close()

    def test_shell_uses_exact_registered_entrypoint_when_bins_overlap(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / 'workspace'
            workspace.mkdir()
            bins = [base / 'one' / 'bin', base / 'two' / 'bin']
            for directory in bins:
                directory.mkdir(parents=True)
                for name in ['npm', 'pnpm']:
                    executable = directory / name
                    executable.write_text(f'#!/bin/sh\necho {directory.parent.name}-{name}\n')
                    executable.chmod(0o700)
            records = [register_toolchain('npm', str(bins[0] / 'npm'), []),
                       register_toolchain('pnpm', str(bins[1] / 'pnpm'), [])]
            runtime = Runtime(workspace, toolchains=records, permission_broker_from_env=False)
            try:
                result = runtime.exec_command({'cmd': 'pnpm --version'})
                self.assertEqual(result['stdout'], 'two-pnpm\n', result)
                result = runtime.exec_command({'cmd': 'npm --version'})
                self.assertEqual(result['stdout'], 'one-npm\n', result)
            finally:
                runtime.close()

    def test_legacy_version_metadata_is_informational_not_an_execution_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = {**self.record, 'version': 'different-version'}
            runtime = Runtime(Path(temporary), toolchains=[record])
            runtime.close()


if __name__ == '__main__':
    unittest.main()
