from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent_runtime.errors import ToolError
from agent_runtime.permissions.context import ACTIVE_PERMISSIONS
from agent_runtime.runtime import Runtime
from agent_runtime.toolchains.resolver import ToolchainResolver


class ToolchainCleanupTests(unittest.TestCase):
    def test_path_lookup_is_metadata_only_even_in_dangerous_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            tools = root / 'user-tools'
            tools.mkdir()
            tool = tools / 'custom-tool'
            tool.write_text('#!/bin/sh\nexit 0\n')
            tool.chmod(0o700)
            with patch.dict(os.environ, {'PATH': str(tools), 'SHELL': '/never/run/login-shell'}), \
                 patch('subprocess.run') as run:
                safe = ToolchainResolver(root, safe_path=[])
                self.assertIsNone(safe.resolve_program('custom-tool'))
                dangerous = ToolchainResolver(root, safe_path=[], unrestricted=True)
                self.assertEqual(dangerous.resolve_program('custom-tool'), str(tool))
                self.assertIsNone(dangerous.resolve_program('not-installed'))
            run.assert_not_called()

    def test_legacy_permission_cannot_change_safe_path_or_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runtime = Runtime(root, permission_broker_from_env=False)
            try:
                before = runtime._command_env({})
                token = ACTIVE_PERMISSIONS.set(frozenset({'privileged_executable'}))
                try:
                    after = runtime._command_env({})
                    self.assertEqual(after['PATH'], before['PATH'])
                    self.assertEqual(after['HOME'], before['HOME'])
                    with self.assertRaises(ToolError) as raised:
                        runtime._resolve_program('no-such-unregistered-tool')
                    self.assertEqual(raised.exception.code, 'HOST_TOOL_RESOLUTION_REQUIRED')
                finally:
                    ACTIVE_PERMISSIONS.reset(token)
            finally:
                runtime.close()

    def test_version_probes_do_not_supply_temporary_read_grants(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runtime = Runtime(root, permission_broker_from_env=False)
            try:
                with patch.object(runtime.process_sandbox, 'wrap', return_value=['test']) as wrap, \
                     patch('subprocess.run') as run:
                    runtime._run_toolchain_probe(['/outside/tool', '--version'], {}, 1)
                wrap.assert_called_once_with(['/outside/tool', '--version'], cwd=root)
                run.assert_called_once()
            finally:
                runtime.close()

    def test_reported_installation_root_never_expands_sandbox(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fake = {'toolchains': {'node': {'selected': {'root': '/'}}}, 'safe_path': []}
            with patch.object(ToolchainResolver, 'discover', return_value=fake):
                runtime = Runtime(root, permission_broker_from_env=False)
            try:
                self.assertNotIn(Path('/'), runtime.toolchain_read_roots)
                self.assertNotIn(Path('/'), getattr(runtime.process_sandbox, 'readable_roots', []))
            finally:
                runtime.close()

    def test_registration_has_priority_over_system_version_hint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / '.python-version').write_text('3.12')
            for directory, program in [('system', 'python3'), ('registered', 'python')]:
                binary = root / directory / 'bin' / program
                binary.parent.mkdir(parents=True)
                binary.write_text('#!/bin/sh\nexit 0\n')
                binary.chmod(0o700)
            registered = root / 'registered/bin/python'
            def probe(argv, env, timeout):
                version = '3.13' if argv[0] == str(registered) else '3.12'
                return subprocess.CompletedProcess(argv, 0, version, '')
            resolver = ToolchainResolver(root, safe_path=[str(root / 'system/bin')],
                                         registered_programs={'python': str(registered)}, probe_runner=probe)
            selected = resolver.discover(['python'])['toolchains']['python']['selected']
            self.assertEqual(selected['source'], 'registered')
            self.assertEqual(selected['version'], '3.13')
