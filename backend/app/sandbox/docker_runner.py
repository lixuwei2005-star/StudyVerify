"""Docker-backed sandbox runner.

Runs the static test wrapper inside a hardened container, one fresh container
per request. Two host files are bind-mounted read-only:

- /sandbox/code.py    — trusted wrapper code (never templated with student source)
- /sandbox/input.json — the per-run JSON payload (code + entry_function + test_cases)

The wrapper reads the payload from STUDYVERIFY_INPUT_PATH=/sandbox/input.json
inside the container. Stdin is intentionally NOT used: docker-py's
attach_socket pattern (sendall + SHUT_WR before container.wait) does not
reliably propagate EOF on Docker Desktop macOS due to vsock proxy half-close
behavior, causing wait() to hang and time out. Bind-mounting the payload as a
file is portable across daemons.

Hardening layers (defense in depth, not a single magic boundary):
network=none, read-only rootfs, capped tmpfs /tmp, pids/cpu/mem cgroups,
ulimits (nproc, nofile), cap_drop=ALL, no-new-privileges, ipc=private,
non-root user, init (tini PID 1), label for cleanup queries.

See docs/specs/step-04-1-docker-sandbox.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import docker
import requests
from docker.errors import APIError, NotFound

from app.sandbox.base_runner import TestRunner

logger = logging.getLogger("app.sandbox")

_KILL_SETTLE_SECONDS = 0.2
_DEAD_CONTAINER_WAIT_SECONDS = 2
_INPUT_ENV_VAR = "STUDYVERIFY_INPUT_PATH"
_CONTAINER_CODE_PATH = "/sandbox/code.py"
_CONTAINER_INPUT_PATH = "/sandbox/input.json"


class DockerCodeRunner(TestRunner):
    """Runs the static test wrapper in an isolated Docker container.

    Each _execute_code() call creates and tears down a fresh container; no
    state persists across runs. Inherits run(SandboxRunRequest) from
    TestRunner, so callers see the same public surface as PythonSubprocessRunner.

    Cancellation note: async cancellation does not abort an in-flight
    container.wait(); the underlying thread continues until wait() returns or
    times out, then `finally` runs cleanup. Containers are still cleaned up,
    just not instantaneously.
    """

    DEFAULT_IMAGE = "python:3.11-slim"

    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        client: docker.DockerClient | None = None,
    ) -> None:
        self.image = image
        self._client = client or docker.from_env()

    async def _execute_code(
        self,
        code: str,
        payload: bytes,
        timeout_seconds: int,
        memory_mb: int,
    ) -> tuple[bytes, bytes, int, bool]:
        return await asyncio.to_thread(
            self._execute_code_sync, code, payload, timeout_seconds, memory_mb
        )

    def _execute_code_sync(
        self,
        code: str,
        payload: bytes,
        timeout_seconds: int,
        memory_mb: int,
    ) -> tuple[bytes, bytes, int, bool]:
        try:
            container: Any = None
            host_code_path: Path | None = None
            host_input_path: Path | None = None

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, prefix="studyverify-sbx-code-"
            ) as f:
                f.write(code)
                host_code_path = Path(f.name)
            # NamedTemporaryFile defaults to 0600 (owner-only). The sandbox
            # container runs as user="nobody" (uid 65534, Step 4 hardening),
            # so on strict Linux hosts nobody cannot read root-owned 0600
            # files mounted in. macOS Docker Desktop maps FS perms loosely
            # via osxfs/VirtioFS so the bug never surfaced in dev. Production
            # Oracle Cloud hit it as: "[Errno 13] Permission denied" on
            # /sandbox/code.py. 0o644 is read-only for non-owners and the
            # bind mount is ro anyway, so write access is impossible.
            os.chmod(host_code_path, 0o644)

            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".json", delete=False, prefix="studyverify-sbx-input-"
            ) as f:
                f.write(payload)
                host_input_path = Path(f.name)
            os.chmod(host_input_path, 0o644)

            container = self._client.containers.create(
                image=self.image,
                command=["python", _CONTAINER_CODE_PATH],
                stdin_open=False,
                detach=True,
                environment={_INPUT_ENV_VAR: _CONTAINER_INPUT_PATH},
                network_mode="none",
                read_only=True,
                tmpfs={"/tmp": "size=64m,noexec"},
                mem_limit=f"{memory_mb}m",
                memswap_limit=f"{memory_mb}m",
                pids_limit=32,
                nano_cpus=1_000_000_000,
                shm_size="8m",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                ipc_mode="private",
                user="nobody",
                init=True,
                labels={"studyverify": "sandbox"},
                ulimits=[
                    docker.types.Ulimit(name="nproc", soft=32, hard=32),
                    docker.types.Ulimit(name="nofile", soft=64, hard=64),
                ],
                volumes={
                    str(host_code_path): {
                        "bind": _CONTAINER_CODE_PATH,
                        "mode": "ro",
                    },
                    str(host_input_path): {
                        "bind": _CONTAINER_INPUT_PATH,
                        "mode": "ro",
                    },
                },
            )

            container.start()

            try:
                wait_result = container.wait(timeout=timeout_seconds)
                exit_code = int(wait_result["StatusCode"])
                timed_out = False
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                # ReadTimeout fires if the SDK gets a clean read timeout;
                # ConnectionError fires when urllib3's ReadTimeoutError is
                # re-raised by requests during response-body read (the path
                # actually observed on Docker Desktop macOS).
                try:
                    container.kill()
                except (APIError, NotFound):
                    pass
                # Brief settle delay before reading logs to avoid racing with
                # kill cleanup and log flushing.
                time.sleep(_KILL_SETTLE_SECONDS)
                try:
                    container.wait(timeout=_DEAD_CONTAINER_WAIT_SECONDS)
                except Exception:
                    pass
                exit_code = -1
                timed_out = True

            stdout = container.logs(stdout=True, stderr=False)
            stderr = container.logs(stdout=False, stderr=True)
            return stdout, stderr, exit_code, timed_out

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except (APIError, NotFound):
                    pass  # already gone
            if host_code_path is not None:
                host_code_path.unlink(missing_ok=True)
            if host_input_path is not None:
                host_input_path.unlink(missing_ok=True)
