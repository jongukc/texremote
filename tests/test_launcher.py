from __future__ import annotations

import unittest

from paperhere.launcher import (
    LaunchError,
    _agent_command,
    _editor_environment,
    _local_editor_command,
    _resolve_remote,
    parse_target,
)


class LauncherTests(unittest.TestCase):
    def test_parses_local_and_ssh_targets(self) -> None:
        self.assertFalse(parse_target("./paper").remote)
        remote = parse_target("mundo:~/code/die")
        self.assertEqual(remote.server, "mundo")
        self.assertEqual(remote.path, "~/code/die")
        uri = parse_target("ssh://user@example.test/home/user/paper")
        self.assertEqual(uri.server, "user@example.test")
        self.assertEqual(uri.path, "/home/user/paper")

    def test_rejects_incomplete_ssh_uri(self) -> None:
        with self.assertRaises(LaunchError):
            parse_target("ssh://mundo")

    def test_resolves_remote_relative_paths(self) -> None:
        self.assertEqual(
            _resolve_remote("/home/me/paper", "out/main.pdf", None),
            "/home/me/paper/out/main.pdf",
        )
        self.assertEqual(
            _resolve_remote("/home/me/paper", "/tmp/main.pdf", None),
            "/tmp/main.pdf",
        )

    def test_agent_command_includes_requested_port_and_bundle(self) -> None:
        command = _agent_command(
            python="/usr/bin/python3",
            bundle="/cache/bundle",
            root="/work/paper",
            token="token",
            pdf="/work/paper/p.pdf",
            nvim_socket="/tmp/nvim.sock",
            nvim="/usr/bin/nvim",
            port=8123,
        )
        self.assertEqual(command[:2], ["env", "PYTHONPATH=/cache/bundle"])
        self.assertIn("8123", command)
        self.assertIn("/work/paper/p.pdf", command)

    def test_editor_environment_is_ephemeral_and_complete(self) -> None:
        environment = _editor_environment(
            host="127.0.0.1",
            port=4321,
            token="secret",
            root="/work/paper",
            nvim_runtime="/opt/paperhere/nvim",
            pdf="/work/paper/p.pdf",
            build_command="make",
            auto_build=True,
        )
        self.assertEqual(environment["PAPERHERE_BUILD_COMMAND"], "make")
        self.assertEqual(environment["PAPERHERE_AUTO_BUILD"], "1")
        self.assertEqual(environment["PAPERHERE_AGENT_PORT"], "4321")
        self.assertEqual(environment["PAPERHERE_NVIM_RUNTIME"], "/opt/paperhere/nvim")

    def test_editor_uses_paperhere_init_wrapper(self) -> None:
        command = _local_editor_command(
            nvim="nvim",
            socket_path="/tmp/nvim.sock",
            bootstrap_path="/opt/paperhere/nvim_bootstrap.lua",
            tex="/work/p.tex",
        )
        self.assertEqual(
            command,
            [
                "nvim",
                "--listen",
                "/tmp/nvim.sock",
                "-u",
                "/opt/paperhere/nvim_bootstrap.lua",
                "/work/p.tex",
            ],
        )


if __name__ == "__main__":
    unittest.main()
