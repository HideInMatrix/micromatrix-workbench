"""Local desktop confirmation surface; deliberately not exposed as MCP tools."""
from __future__ import annotations

from agent_runtime.toolchains.registration import prepare_toolchain, register_toolchain


class ToolchainAPI:
    def inspect_toolchain(self, program: str, executable: str, read_roots: list[str]) -> dict:
        return prepare_toolchain(program, executable, read_roots)

    def register_toolchain(self, program: str, executable: str, read_roots: list[str]) -> dict:
        return register_toolchain(program, executable, read_roots, confirmed_roots=read_roots)
