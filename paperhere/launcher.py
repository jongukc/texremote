from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO
from urllib.error import URLError
from urllib.request import urlopen

from .agent import find_main_tex


REMOTE_TARGET = re.compile(r"^(?P<server>(?:[^/@:]+@)?[^/:]+):(?P<path>.+)$")


class LaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    server: str | None
    path: str

    @property
    def remote(self) -> bool:
        return self.server is not None


@dataclass(frozen=True)
class RemoteInfo:
    root: str
    home: str
    shell: str
    uid: int
    python: str
    nvim: str


def parse_target(value: str) -> Target:
    if value.startswith("ssh://"):
        remainder = value.removeprefix("ssh://")
        server, separator, path = remainder.partition("/")
        if not separator or not server:
            raise LaunchError("SSH targets must look like ssh://host/path")
        return Target(server=server, path="/" + path)
    match = REMOTE_TARGET.match(value)
    if match and not Path(value).exists():
        return Target(server=match.group("server"), path=match.group("path"))
    return Target(server=None, path=value)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _read_ready(process: subprocess.Popen[str], timeout: float = 30) -> dict[str, object]:
    if process.stdout is None:
        raise LaunchError("Agent output is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LaunchError(f"Preview agent exited with status {process.returncode}")
            events = selector.select(timeout=min(0.5, deadline - time.monotonic()))
            if not events:
                continue
            line = process.stdout.readline()
            if not line:
                continue
            if line.startswith("PAPERHERE_READY "):
                try:
                    value = json.loads(line.removeprefix("PAPERHERE_READY "))
                except json.JSONDecodeError as exc:
                    raise LaunchError("Preview agent returned invalid readiness data") from exc
                if isinstance(value, dict):
                    return value
            print(line.rstrip(), file=sys.stderr)
    finally:
        selector.close()
    raise LaunchError("Timed out waiting for the preview agent")


def _wait_for_server(url: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            error = exc
        time.sleep(0.1)
    raise LaunchError(f"Preview server did not become ready: {error}")


def _runtime_directory() -> Path:
    parent = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    path = Path(tempfile.mkdtemp(prefix=f"paperhere-{os.getuid()}-", dir=parent))
    path.chmod(0o700)
    return path


def _package_directory() -> Path:
    return Path(__file__).resolve().parent


def _bundle_digest(package: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(str(path.relative_to(package)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class SshSession:
    def __init__(self, server: str, runtime: Path) -> None:
        self.server = server
        self.control = runtime / "ssh"
        self.master: subprocess.Popen[str] | None = None

    def start(self) -> None:
        command = [
            "ssh",
            "-M",
            "-S",
            str(self.control),
            "-o",
            "ControlPersist=no",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-N",
            self.server,
        ]
        self.master = subprocess.Popen(command, text=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.master.poll() is not None:
                raise LaunchError(f"SSH connection failed with status {self.master.returncode}")
            if self.control.exists():
                check = subprocess.run(
                    ["ssh", "-S", str(self.control), "-O", "check", self.server],
                    capture_output=True,
                    text=True,
                )
                if check.returncode == 0:
                    return
            time.sleep(0.1)
        raise LaunchError("Timed out establishing the SSH connection")

    def base_command(self) -> list[str]:
        return ["ssh", "-S", str(self.control)]

    def capture(self, remote_command: str) -> str:
        result = subprocess.run(
            [*self.base_command(), self.server, remote_command],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise LaunchError(f"Remote command failed: {detail}")
        return result.stdout

    def forward(self, local_port: int, remote_port: int) -> None:
        result = subprocess.run(
            [
                *self.base_command(),
                "-O",
                "forward",
                "-L",
                f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
                self.server,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or "unknown SSH forwarding error"
            raise LaunchError(f"Cannot forward the preview port: {detail}")

    def popen(
        self,
        remote_command: str,
        *,
        tty: bool = False,
        stdout: int | IO[str] | None = None,
    ) -> subprocess.Popen[str]:
        command = [*self.base_command()]
        if tty:
            command.append("-tt")
        else:
            command.append("-T")
        command.extend([self.server, remote_command])
        return subprocess.Popen(command, stdout=stdout, text=True)

    def close(self) -> None:
        if self.master is None:
            return
        if self.master.poll() is None:
            subprocess.run(
                ["ssh", "-S", str(self.control), "-O", "exit", self.server],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _stop_process(self.master)


def _probe_remote(ssh: SshSession, requested_root: str, nvim: str | None) -> RemoteInfo:
    probe = (
        "import json,os,pathlib,sys;"
        "root=pathlib.Path(os.path.expanduser(sys.argv[1])).resolve();"
        "print(json.dumps({'root':str(root),'is_dir':root.is_dir(),"
        "'home':str(pathlib.Path.home()),'shell':os.environ.get('SHELL','/bin/sh'),"
        "'uid':os.getuid()}))"
    )
    output = ssh.capture(f"python3 -c {shlex.quote(probe)} {shlex.quote(requested_root)}")
    try:
        data = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        raise LaunchError("Could not inspect the remote project") from exc
    if not data.get("is_dir"):
        raise LaunchError(f"Not a remote project directory: {data.get('root')}")
    python_path = ssh.capture("command -v python3").strip()
    if not python_path:
        raise LaunchError("Python 3 is required on the remote host")
    nvim_path = nvim
    if not nvim_path:
        direct = ssh.capture("command -v nvim || true").strip()
        if direct:
            nvim_path = direct.splitlines()[-1]
        else:
            login_command = shlex.join([str(data["shell"]), "-lic", "command -v nvim"])
            discovered = ssh.capture(login_command).strip()
            paths = [line for line in discovered.splitlines() if line.startswith("/")]
            nvim_path = paths[-1] if paths else None
    if not nvim_path:
        raise LaunchError("Neovim was not found, including through the remote login shell")
    return RemoteInfo(
        root=str(data["root"]),
        home=str(data["home"]),
        shell=str(data["shell"]),
        uid=int(data["uid"]),
        python=python_path,
        nvim=nvim_path,
    )


def _deploy(ssh: SshSession, info: RemoteInfo, runtime: Path) -> str:
    package = _package_directory()
    digest = _bundle_digest(package)
    parent = PurePosixPath(info.home) / ".cache" / "paperhere" / "bundles"
    target = parent / digest
    complete = target / ".complete"
    check = ssh.capture(f"test -f {shlex.quote(str(complete))} && echo ready || true")
    if check.strip() == "ready":
        return str(target)

    archive = runtime / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(package.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            bundle.add(path, arcname=Path("paperhere") / path.relative_to(package))
    temporary = parent / f".{digest}-{uuid.uuid4().hex[:8]}"
    stale = parent / f".{digest}-stale-{uuid.uuid4().hex[:8]}"
    command = " && ".join(
        [
            "umask 077",
            f"mkdir -p {shlex.quote(str(parent))} {shlex.quote(str(temporary))}",
            f"tar -xzf - -C {shlex.quote(str(temporary))}",
            f"touch {shlex.quote(str(temporary / '.complete'))}",
            f"if test -e {shlex.quote(str(target))}; then mv {shlex.quote(str(target))} {shlex.quote(str(stale))}; fi",
            f"mv {shlex.quote(str(temporary))} {shlex.quote(str(target))}",
        ]
    )
    with archive.open("rb") as stream:
        result = subprocess.run(
            [*ssh.base_command(), "-T", ssh.server, command],
            stdin=stream,
            capture_output=True,
            text=False,
        )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise LaunchError(f"Could not deploy Paperhere: {detail}")
    return str(target)


def _remote_discover(ssh: SshSession, info: RemoteInfo, bundle: str) -> str | None:
    command = (
        f"PYTHONPATH={shlex.quote(bundle)} {shlex.quote(info.python)} "
        f"-m paperhere.agent discover --root {shlex.quote(info.root)}"
    )
    output = ssh.capture(command)
    try:
        data = json.loads(output.strip())
    except json.JSONDecodeError as exc:
        raise LaunchError("Remote TeX discovery returned invalid data") from exc
    tex = data.get("tex")
    return str(tex) if tex else None


def _resolve_remote(root: str, value: str | None, default: str | None) -> str | None:
    selected = value or default
    if selected is None:
        return None
    path = PurePosixPath(selected)
    return str(path if path.is_absolute() else PurePosixPath(root) / path)


def _agent_command(
    *,
    python: str,
    bundle: str | None,
    root: str,
    token: str,
    pdf: str | None,
    nvim_socket: str,
    nvim: str,
    port: int = 0,
) -> list[str]:
    command = [
        python,
        "-m",
        "paperhere.agent",
        "serve",
        "--root",
        root,
        "--token",
        token,
        "--port",
        str(port),
    ]
    if pdf:
        command.extend(["--pdf", pdf])
    command.extend(["--nvim-socket", nvim_socket, "--nvim", nvim])
    if bundle:
        return ["env", f"PYTHONPATH={bundle}", *command]
    return command


def _editor_environment(
    *,
    host: str,
    port: int,
    token: str,
    root: str,
    nvim_runtime: str,
    pdf: str | None,
    build_command: str | None,
    auto_build: bool,
) -> dict[str, str]:
    environment = {
        "PAPERHERE_AGENT_HOST": host,
        "PAPERHERE_AGENT_PORT": str(port),
        "PAPERHERE_TOKEN": token,
        "PAPERHERE_ROOT": root,
        "PAPERHERE_NVIM_RUNTIME": nvim_runtime,
        "PAPERHERE_AUTO_BUILD": "1" if auto_build else "0",
    }
    if pdf:
        environment["PAPERHERE_PDF"] = pdf
    if build_command:
        environment["PAPERHERE_BUILD_COMMAND"] = build_command
    return environment


def _local_editor_command(
    *, nvim: str, socket_path: str, bootstrap_path: str, tex: str | None
) -> list[str]:
    target = tex or "."
    return [
        nvim,
        "--listen",
        socket_path,
        "-u",
        bootstrap_path,
        target,
    ]


def run_open(args) -> None:
    target = parse_target(args.target)
    runtime = _runtime_directory()
    token = uuid.uuid4().hex + uuid.uuid4().hex
    ssh: SshSession | None = None
    agent: subprocess.Popen[str] | None = None
    editor: subprocess.Popen[str] | None = None
    remote_runtime: str | None = None
    remote_agent_pid: int | None = None
    remote_editor_command: str | None = None
    local_editor_args: list[str] | None = None
    local_editor_cwd: Path | None = None
    local_editor_environment: dict[str, str] | None = None
    exit_code = 0
    try:
        if target.remote:
            assert target.server is not None
            ssh = SshSession(target.server, runtime)
            ssh.start()
            info = _probe_remote(ssh, target.path, args.nvim)
            bundle = _deploy(ssh, info, runtime)
            discovered = _remote_discover(ssh, info, bundle)
            tex = _resolve_remote(info.root, args.tex, discovered)
            default_pdf = str(PurePosixPath(tex).with_suffix(".pdf")) if tex else None
            pdf = _resolve_remote(info.root, args.pdf, default_pdf)
            remote_runtime = f"/tmp/paperhere-{info.uid}/{uuid.uuid4().hex[:12]}"
            nvim_socket = f"{remote_runtime}/nvim.sock"
            ssh.capture(f"umask 077; mkdir -p {shlex.quote(remote_runtime)}")
            command = _agent_command(
                python=info.python,
                bundle=bundle,
                root=info.root,
                token=token,
                pdf=pdf,
                nvim_socket=nvim_socket,
                nvim=info.nvim,
                port=0,
            )
            agent = ssh.popen(shlex.join(command), stdout=subprocess.PIPE)
            ready = _read_ready(agent)
            remote_port = int(ready["port"])
            remote_agent_pid = int(ready["pid"])
            local_port = args.port or _free_port()
            ssh.forward(local_port, remote_port)
            server_url = f"http://127.0.0.1:{local_port}"
            editor_environment = _editor_environment(
                host="127.0.0.1",
                port=remote_port,
                token=token,
                root=info.root,
                nvim_runtime=str(PurePosixPath(bundle) / "paperhere" / "nvim"),
                pdf=pdf,
                build_command=args.build_cmd,
                auto_build=not args.no_auto_build,
            )
            editor_args = [
                info.nvim,
                "--listen",
                nvim_socket,
                "-u",
                str(PurePosixPath(bundle) / "paperhere" / "nvim_bootstrap.lua"),
                tex or info.root,
            ]
            inner = "cd " + shlex.quote(info.root) + " && exec " + shlex.join(
                ["env", *[f"{key}={value}" for key, value in editor_environment.items()], *editor_args]
            )
            # The executable was already resolved through an interactive login
            # shell during probing. The actual editor shell stays non-interactive
            # so prompt plugins cannot block an SSH launch.
            remote_editor_command = shlex.join([info.shell, "-lc", inner])
        else:
            root = Path(target.path).expanduser().resolve()
            if not root.is_dir():
                raise LaunchError(f"Not a project directory: {root}")
            discovered_path = find_main_tex(root)
            tex_path = Path(args.tex) if args.tex else discovered_path
            if tex_path and not tex_path.is_absolute():
                tex_path = root / tex_path
            pdf_path = Path(args.pdf) if args.pdf else (tex_path.with_suffix(".pdf") if tex_path else None)
            if pdf_path and not pdf_path.is_absolute():
                pdf_path = root / pdf_path
            nvim = args.nvim or shutil.which("nvim")
            if not nvim:
                raise LaunchError("Neovim was not found")
            nvim_socket = str(runtime / "nvim.sock")
            command = _agent_command(
                python=sys.executable,
                bundle=None,
                root=str(root),
                token=token,
                pdf=str(pdf_path) if pdf_path else None,
                nvim_socket=nvim_socket,
                nvim=nvim,
                port=args.port or 0,
            )
            agent = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
            ready = _read_ready(agent)
            local_port = int(ready["port"])
            server_url = f"http://127.0.0.1:{local_port}"
            editor_environment = os.environ.copy()
            editor_environment.update(
                _editor_environment(
                    host="127.0.0.1",
                    port=local_port,
                    token=token,
                    root=str(root),
                    nvim_runtime=str(_package_directory() / "nvim"),
                    pdf=str(pdf_path) if pdf_path else None,
                    build_command=args.build_cmd,
                    auto_build=not args.no_auto_build,
                )
            )
            local_editor_args = _local_editor_command(
                nvim=nvim,
                socket_path=nvim_socket,
                bootstrap_path=str(_package_directory() / "nvim_bootstrap.lua"),
                tex=str(tex_path) if tex_path else None,
            )
            local_editor_cwd = root
            local_editor_environment = editor_environment

        viewer_url = f"{server_url}/?token={token}"
        _wait_for_server(f"{server_url}/api/status?token={token}")
        print(f"Paperhere preview: {viewer_url}")
        if not args.no_browser:
            webbrowser.open(viewer_url)

        if not args.no_editor:
            if target.remote:
                assert ssh is not None and remote_editor_command is not None
                editor = ssh.popen(remote_editor_command, tty=True)
            else:
                assert local_editor_args is not None and local_editor_cwd is not None
                editor = subprocess.Popen(
                    local_editor_args,
                    cwd=local_editor_cwd,
                    env=local_editor_environment,
                    text=True,
                )

        if editor is not None:
            exit_code = editor.wait()
        else:
            print("Preview server is running; press Ctrl-C to stop.")
            while agent.poll() is None:
                time.sleep(0.5)
            exit_code = agent.returncode or 0
    except KeyboardInterrupt:
        exit_code = 130
    except LaunchError as exc:
        print(f"paperhere: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        _stop_process(editor)
        if ssh is not None:
            if remote_agent_pid is not None:
                try:
                    cleanup = (
                        f"args=$(ps -p {remote_agent_pid} -o args= 2>/dev/null || true); "
                        f"case \"$args\" in *{token}*) "
                        f"kill -TERM -- {remote_agent_pid} 2>/dev/null || true;; esac"
                    )
                    ssh.capture(cleanup)
                except LaunchError as exc:
                    print(f"paperhere: remote agent cleanup failed: {exc}", file=sys.stderr)
        _stop_process(agent)
        if ssh is not None:
            if remote_runtime is not None:
                try:
                    ssh.capture(f"rmdir -- {shlex.quote(remote_runtime)} 2>/dev/null || true")
                except LaunchError:
                    pass
            ssh.close()
        shutil.rmtree(runtime, ignore_errors=True)
    if exit_code:
        raise SystemExit(exit_code)
