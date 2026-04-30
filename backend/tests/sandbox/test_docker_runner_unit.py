"""Unit tests for DockerCodeRunner — no Docker daemon required.

These tests mock the Docker SDK and verify the runner's contract with it:
- The 14 isolation flags reach containers.create() unweakened.
- create → start → wait → logs ordering on the container.
- Payload reaches the container via a read-only bind-mounted JSON file
  (the bind-mount approach replaces stdin attach due to Docker Desktop
  macOS half-close issues; see docker_runner.py module docstring).
- Timeout path triggers kill + cleanup.
- Exceptions during create / start still trigger all relevant cleanup
  paths (both temp files unlinked, container.remove called when applicable).
- Custom image propagates.
- A successful run produces a populated SandboxRunResult through the base class.

These tests do NOT verify Docker enforces the isolation; that is the
integration suite's job.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import docker
import pytest
import requests
from docker.errors import APIError

from app.sandbox.docker_runner import DockerCodeRunner
from app.sandbox.schemas import SandboxRunRequest


def _wrapper_success_stdout() -> bytes:
    """Stdout the wrapper would emit for one passing test case."""
    return json.dumps(
        [
            {
                "test_index": 0,
                "input": "1",
                "expected": "1",
                "actual": "1",
                "passed": True,
                "error": None,
                "duration_ms": 1,
            }
        ]
    ).encode()


def _make_client(
    *,
    exit_code: int = 0,
    stdout: bytes = b"[]",
    stderr: bytes = b"",
    wait_exception: Exception | None = None,
    create_exception: Exception | None = None,
    start_exception: Exception | None = None,
) -> tuple[MagicMock, MagicMock]:
    client = MagicMock(spec=docker.DockerClient)
    container = MagicMock()

    if create_exception is not None:
        client.containers.create.side_effect = create_exception
    else:
        client.containers.create.return_value = container

    if start_exception is not None:
        container.start.side_effect = start_exception

    if wait_exception is not None:
        container.wait.side_effect = wait_exception
    else:
        container.wait.return_value = {"StatusCode": exit_code}

    container.logs.side_effect = [stdout, stderr]

    return client, container


@pytest.fixture
def basic_request() -> SandboxRunRequest:
    return SandboxRunRequest(
        code="def f(x): return x",
        entry_function="f",
        test_cases=[{"input": "1", "expected": "1"}],
        timeout_seconds=5,
        memory_mb=64,
    )


# ---------------------------------------------------------------------------
# 1. The 14 hardening flags reach containers.create() — central security claim.
# ---------------------------------------------------------------------------
async def test_runner_passes_correct_isolation_flags(basic_request: SandboxRunRequest) -> None:
    client, _ = _make_client(stdout=_wrapper_success_stdout())
    runner = DockerCodeRunner(client=client)

    await runner.run(basic_request)

    assert client.containers.create.call_count == 1
    kwargs = client.containers.create.call_args.kwargs

    # Image + command + payload-delivery wiring
    assert kwargs["image"] == "python:3.11-slim"
    assert kwargs["command"] == ["python", "/sandbox/code.py"]
    assert kwargs["stdin_open"] is False
    assert kwargs["detach"] is True
    assert kwargs["environment"] == {"STUDYVERIFY_INPUT_PATH": "/sandbox/input.json"}

    # 14 hardening flags — assert each by name. If a future change weakens
    # any of these, this test must fail loudly.
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["tmpfs"] == {"/tmp": "size=64m,noexec"}
    assert kwargs["mem_limit"] == "64m"
    assert kwargs["memswap_limit"] == "64m"
    assert kwargs["pids_limit"] == 32
    assert kwargs["nano_cpus"] == 1_000_000_000
    assert kwargs["shm_size"] == "8m"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["ipc_mode"] == "private"
    assert kwargs["user"] == "nobody"
    assert kwargs["init"] is True
    assert kwargs["labels"] == {"studyverify": "sandbox"}

    ulimits = kwargs["ulimits"]
    assert len(ulimits) == 2
    # docker.types.Ulimit is a dict subclass with capitalized keys
    nproc = next(u for u in ulimits if u["Name"] == "nproc")
    nofile = next(u for u in ulimits if u["Name"] == "nofile")
    assert nproc["Soft"] == 32 and nproc["Hard"] == 32
    assert nofile["Soft"] == 64 and nofile["Hard"] == 64

    volumes = kwargs["volumes"]
    assert len(volumes) == 2
    code_mount = next(m for h, m in volumes.items() if Path(h).suffix == ".py")
    input_mount = next(m for h, m in volumes.items() if Path(h).suffix == ".json")
    assert code_mount == {"bind": "/sandbox/code.py", "mode": "ro"}
    assert input_mount == {"bind": "/sandbox/input.json", "mode": "ro"}


# ---------------------------------------------------------------------------
# 2. create → start → wait → logs ordering on the container.
# ---------------------------------------------------------------------------
async def test_runner_uses_create_start_wait_order(basic_request: SandboxRunRequest) -> None:
    client, container = _make_client(stdout=_wrapper_success_stdout())
    runner = DockerCodeRunner(client=client)

    await runner.run(basic_request)

    method_names = [c[0] for c in container.method_calls]
    # First two calls on the container, in order, must be:
    assert method_names[:2] == ["start", "wait"]
    # Logs follow wait, before remove
    assert method_names.index("wait") < method_names.index("logs")
    assert method_names.index("logs") < method_names.index("remove")
    # And containers.create() preceded any container method call
    assert client.containers.create.call_count == 1
    # attach_socket is not used in the bind-mount design
    container.attach_socket.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Payload reaches the container via a bind-mounted file (not stdin).
# ---------------------------------------------------------------------------
async def test_runner_passes_payload_via_bind_mount(basic_request: SandboxRunRequest) -> None:
    client, _ = _make_client(stdout=_wrapper_success_stdout())
    runner = DockerCodeRunner(client=client)

    # Capture the input host path before the runner's finally block unlinks it.
    captured_input_bytes: dict[str, bytes] = {}

    def _capture(*, image, **kwargs):
        volumes = kwargs["volumes"]
        input_host_path = next(h for h in volumes if Path(h).suffix == ".json")
        captured_input_bytes["payload"] = Path(input_host_path).read_bytes()
        return client.containers.create.return_value

    client.containers.create.side_effect = _capture

    await runner.run(basic_request)

    # The base class builds payload = json.dumps({code, entry_function, test_cases}).encode()
    expected_payload = json.dumps(
        {
            "code": basic_request.code,
            "entry_function": basic_request.entry_function,
            "test_cases": basic_request.test_cases,
        }
    ).encode()

    assert captured_input_bytes["payload"] == expected_payload

    # And the env var pointing the wrapper at the file is set:
    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["environment"]["STUDYVERIFY_INPUT_PATH"] == "/sandbox/input.json"
    # The file was bind-mounted read-only:
    input_mount = next(m for h, m in kwargs["volumes"].items() if Path(h).suffix == ".json")
    assert input_mount["mode"] == "ro"


# ---------------------------------------------------------------------------
# 4. Successful run produces a populated SandboxRunResult through the base class.
# ---------------------------------------------------------------------------
async def test_runner_returns_sandbox_run_result_on_success(
    basic_request: SandboxRunRequest,
) -> None:
    client, _ = _make_client(exit_code=0, stdout=_wrapper_success_stdout())
    runner = DockerCodeRunner(client=client)

    result = await runner.run(basic_request)

    assert result.status == "all_passed"
    assert result.pass_count == 1
    assert result.fail_count == 0
    assert len(result.test_results) == 1
    assert result.test_results[0].passed is True
    assert result.test_results[0].actual == "1"


# ---------------------------------------------------------------------------
# 5. Timeout path: wait raises ReadTimeout → kill, settle, cleanup, status=timeout.
# ---------------------------------------------------------------------------
async def test_runner_handles_timeout(basic_request: SandboxRunRequest) -> None:
    client, container = _make_client(
        wait_exception=requests.exceptions.ReadTimeout("read timed out"),
        stdout=b"",
        stderr=b"",
    )
    runner = DockerCodeRunner(client=client)

    result = await runner.run(basic_request)

    assert result.status == "timeout"
    assert result.test_results == []
    container.kill.assert_called_once()
    # Cleanup still runs even after timeout
    container.remove.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# 5b. Timeout path also fires when the SDK raises ConnectionError (the actual
# exception observed on Docker Desktop macOS when wait() reads time out).
# ---------------------------------------------------------------------------
async def test_runner_handles_connection_error_as_timeout(
    basic_request: SandboxRunRequest,
) -> None:
    client, container = _make_client(
        wait_exception=requests.exceptions.ConnectionError("read timed out"),
        stdout=b"",
        stderr=b"",
    )
    runner = DockerCodeRunner(client=client)

    result = await runner.run(basic_request)

    assert result.status == "timeout"
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# 6. create() raises → no container cleanup attempt; both tempfiles unlinked.
# ---------------------------------------------------------------------------
async def test_runner_cleans_up_on_create_exception(
    basic_request: SandboxRunRequest,
) -> None:
    client, container = _make_client(create_exception=APIError("boom"))
    runner = DockerCodeRunner(client=client)

    with pytest.raises(APIError):
        await runner.run(basic_request)

    # Container was never returned, so no remove call against an uninitialized object.
    container.remove.assert_not_called()

    # Both host paths are constructed before create() is called; even though
    # create() raised, the kwarg dict was still recorded by the mock — and the
    # runner's finally block must have unlinked both.
    kwargs = client.containers.create.call_args.kwargs
    for host_path in kwargs["volumes"]:
        assert not Path(host_path).exists(), (
            f"tempfile {host_path} must be cleaned up on create() failure"
        )


# ---------------------------------------------------------------------------
# 7. start() raises → container.remove called, both tempfiles unlinked.
# ---------------------------------------------------------------------------
async def test_runner_cleans_up_on_start_exception(
    basic_request: SandboxRunRequest,
) -> None:
    client, container = _make_client(start_exception=APIError("start failed"))
    runner = DockerCodeRunner(client=client)

    with pytest.raises(APIError):
        await runner.run(basic_request)

    # Container was created, so it must be force-removed.
    container.remove.assert_called_once_with(force=True)

    kwargs = client.containers.create.call_args.kwargs
    for host_path in kwargs["volumes"]:
        assert not Path(host_path).exists(), (
            f"tempfile {host_path} must be cleaned up on start() failure"
        )


# ---------------------------------------------------------------------------
# 8. Custom image propagates to containers.create().
# ---------------------------------------------------------------------------
async def test_runner_uses_custom_image(basic_request: SandboxRunRequest) -> None:
    client, _ = _make_client(stdout=_wrapper_success_stdout())
    runner = DockerCodeRunner(image="my-image:tag", client=client)

    await runner.run(basic_request)

    kwargs = client.containers.create.call_args.kwargs
    assert kwargs["image"] == "my-image:tag"
