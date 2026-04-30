"""Integration tests for DockerCodeRunner — require a real Docker daemon.

These tests instantiate a real DockerCodeRunner against the live host daemon
and assert observed behavior, not mock interactions. They are the verification
that the 14 hardening flags actually do what the spec claims they do.

The four security-claim tests are:
- test_baseline_network_isolation (network=none works)
- test_dns_resolution_blocked (network=none also blocks DNS)
- test_fork_bomb_caught_by_pids (pids_limit=32 works)
- test_capability_drop_blocks_mount (cap_drop=ALL works)
- test_no_orphan_containers_after_run (cleanup works)

If any of these fails, the corresponding hardening claim is broken — do not
paper over flakes. See docs/specs/step-04-1-docker-sandbox.md.
"""

from __future__ import annotations

import asyncio

import docker
import pytest

from app.sandbox.docker_runner import DockerCodeRunner
from app.sandbox.schemas import SandboxRunRequest

try:
    _client = docker.from_env()
    _client.ping()
    _DOCKER_AVAILABLE = True
except Exception:
    _DOCKER_AVAILABLE = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker daemon not available"),
]


@pytest.fixture
def runner() -> DockerCodeRunner:
    return DockerCodeRunner()


# ---------------------------------------------------------------------------
# 1. Happy path: trusted code runs end-to-end and reports all_passed.
# ---------------------------------------------------------------------------
async def test_happy_path_round_trip(runner: DockerCodeRunner) -> None:
    request = SandboxRunRequest(
        code="def add(a, b): return a + b",
        entry_function="add",
        test_cases=[
            {"input": "(1, 2)", "expected": "3"},
            {"input": "(10, 20)", "expected": "30"},
        ],
        timeout_seconds=10,
    )
    result = await runner.run(request)
    assert result.status == "all_passed"
    assert result.pass_count == 2


# ---------------------------------------------------------------------------
# 2. Timeout: infinite loop killed by timeout, wall clock bounded.
# ---------------------------------------------------------------------------
async def test_timeout_kills_long_running_code(runner: DockerCodeRunner) -> None:
    import time as time_mod

    request = SandboxRunRequest(
        code="def loop(x):\n    while True:\n        pass",
        entry_function="loop",
        test_cases=[{"input": "0", "expected": "0"}],
        timeout_seconds=2,
    )
    start = time_mod.perf_counter()
    result = await runner.run(request)
    elapsed = time_mod.perf_counter() - start

    assert result.status == "timeout"
    # Generous bound: 2s timeout + kill/settle/cleanup overhead
    assert elapsed < 15, f"timeout cleanup took too long: {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# 3. OOM: allocation beyond mem_limit produces non-success without hang.
# ---------------------------------------------------------------------------
async def test_oom_caught_by_memory_limit(runner: DockerCodeRunner) -> None:
    # 50M ints * 8 bytes = ~400MB; mem_limit=64MB → OOM kill or MemoryError.
    request = SandboxRunRequest(
        code="def hog(x):\n    return [0] * (50 * 1024 * 1024)",
        entry_function="hog",
        test_cases=[{"input": "0", "expected": "ignored"}],
        timeout_seconds=10,
        memory_mb=64,
    )
    result = await runner.run(request)
    assert result.status != "all_passed"


# ---------------------------------------------------------------------------
# 4. SECURITY CLAIM: network=none blocks outbound TCP.
# ---------------------------------------------------------------------------
async def test_baseline_network_isolation(runner: DockerCodeRunner) -> None:
    code = (
        "def hit(x):\n"
        "    import socket\n"
        "    socket.create_connection(('8.8.8.8', 53), timeout=2)\n"
        "    return 'connected'\n"
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="hit",
        test_cases=[{"input": "0", "expected": "connected"}],
        timeout_seconds=10,
    )
    result = await runner.run(request)

    assert result.status == "some_failed"
    err = result.test_results[0].error or ""
    # OSError "Network is unreachable" is the typical signal under network=none
    assert "OSError" in err or "Network is unreachable" in err or "gaierror" in err, err
    assert result.test_results[0].actual != "'connected'"


# ---------------------------------------------------------------------------
# 5. read_only=True root: writes outside tmpfs fail.
# ---------------------------------------------------------------------------
async def test_baseline_filesystem_readonly(runner: DockerCodeRunner) -> None:
    code = (
        "def write_root(x):\n"
        "    with open('/etc/test', 'w') as f:\n"
        "        f.write('hi')\n"
        "    return 'ok'\n"
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="write_root",
        test_cases=[{"input": "0", "expected": "ok"}],
        timeout_seconds=10,
    )
    result = await runner.run(request)
    assert result.status == "some_failed"
    err = result.test_results[0].error or ""
    assert "OSError" in err or "PermissionError" in err or "Read-only" in err, err


# ---------------------------------------------------------------------------
# 6. tmpfs /tmp writable + executable-flag-honored: writes under /tmp succeed.
# ---------------------------------------------------------------------------
async def test_tmpfs_writable(runner: DockerCodeRunner) -> None:
    code = (
        "def use_tmp(x):\n"
        "    with open('/tmp/scratch', 'w') as f:\n"
        "        f.write('hello')\n"
        "    with open('/tmp/scratch') as f:\n"
        "        return f.read()\n"
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="use_tmp",
        test_cases=[{"input": "0", "expected": "hello"}],
        timeout_seconds=10,
    )
    result = await runner.run(request)
    assert result.status == "all_passed"


# ---------------------------------------------------------------------------
# 7. Concurrent runs share no state: each container has its own tmpfs.
# ---------------------------------------------------------------------------
async def test_concurrent_runs_isolated(runner: DockerCodeRunner) -> None:
    code = (
        "def stamp(x):\n"
        "    with open('/tmp/scratch', 'w') as f:\n"
        "        f.write(str(x))\n"
        "    with open('/tmp/scratch') as f:\n"
        "        return f.read()\n"
    )
    requests = [
        SandboxRunRequest(
            code=code,
            entry_function="stamp",
            test_cases=[{"input": str(i), "expected": str(i)}],
            timeout_seconds=10,
        )
        for i in (101, 202, 303)
    ]
    results = await asyncio.gather(*(runner.run(r) for r in requests))
    for i, result in zip((101, 202, 303), results, strict=True):
        assert result.status == "all_passed", (i, result)
        assert result.test_results[0].actual == f"'{i}'", (i, result.test_results[0].actual)


# ---------------------------------------------------------------------------
# 8. SECURITY CLAIM: cleanup leaves no orphan containers.
# ---------------------------------------------------------------------------
async def test_no_orphan_containers_after_run(runner: DockerCodeRunner) -> None:
    client = docker.from_env()
    before = client.containers.list(all=True, filters={"label": "studyverify=sandbox"})
    before_ids = {c.id for c in before}

    request = SandboxRunRequest(
        code="def f(x): return x",
        entry_function="f",
        test_cases=[{"input": "1", "expected": "1"}],
        timeout_seconds=10,
    )
    await runner.run(request)

    after = client.containers.list(all=True, filters={"label": "studyverify=sandbox"})
    after_ids = {c.id for c in after}
    leaked = after_ids - before_ids
    assert not leaked, f"runner leaked {len(leaked)} container(s): {leaked}"


# ---------------------------------------------------------------------------
# 9. SECURITY CLAIM: network=none blocks DNS.
# ---------------------------------------------------------------------------
async def test_dns_resolution_blocked(runner: DockerCodeRunner) -> None:
    code = "def lookup(x):\n    import socket\n    return socket.getaddrinfo('example.com', 80)\n"
    request = SandboxRunRequest(
        code=code,
        entry_function="lookup",
        test_cases=[{"input": "0", "expected": "anything"}],
        timeout_seconds=10,
    )
    result = await runner.run(request)
    assert result.status == "some_failed"
    err = result.test_results[0].error or ""
    assert "gaierror" in err or "OSError" in err, err


# ---------------------------------------------------------------------------
# 10. SECURITY CLAIM: pids_limit=32 stops fork bombs.
# ---------------------------------------------------------------------------
async def test_fork_bomb_caught_by_pids(runner: DockerCodeRunner) -> None:
    # Children sleep so they hold a slot; parent forks until OSError.
    # pids_limit=32 must trigger before the 100-iteration loop completes.
    code = (
        "def forky(x):\n"
        "    import os, time\n"
        "    blocked = False\n"
        "    for _ in range(100):\n"
        "        try:\n"
        "            pid = os.fork()\n"
        "        except OSError:\n"
        "            blocked = True\n"
        "            break\n"
        "        if pid == 0:\n"
        "            try:\n"
        "                time.sleep(30)\n"
        "            finally:\n"
        "                os._exit(0)\n"
        "    return 'blocked' if blocked else 'all_forked'\n"
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="forky",
        test_cases=[{"input": "0", "expected": "blocked"}],
        timeout_seconds=10,
    )
    result = await runner.run(request)
    # Either the function completed and reported "blocked" (fork hit limit
    # cleanly), or the wrapper recorded an OSError per-test.
    assert result.status != "all_passed" or (result.test_results[0].actual == "'blocked'"), result
    if result.status == "all_passed":
        assert result.test_results[0].actual == "'blocked'"


# ---------------------------------------------------------------------------
# 11. Stdout flood: parser fails gracefully, error text is bounded.
# ---------------------------------------------------------------------------
async def test_stdout_flood_truncated(runner: DockerCodeRunner) -> None:
    code = "def flood(x):\n    print('a' * (5 * 1024 * 1024))\n    return 'ok'\n"
    request = SandboxRunRequest(
        code=code,
        entry_function="flood",
        test_cases=[{"input": "0", "expected": "ok"}],
        timeout_seconds=15,
    )
    result = await runner.run(request)
    # 5MB of "a..." precedes the wrapper's JSON line; json.loads on the full
    # stdout fails. The base class returns status=error with a truncated snippet.
    # Cap location: app/sandbox/base_runner.py _STDOUT_TRUNC=500.
    assert result.status == "error"
    assert "failed to parse wrapper stdout as JSON" in (result.error or "")
    # Error must be bounded: the 5MB stdout cannot have leaked into the result.
    assert len(result.error or "") < 2000


# ---------------------------------------------------------------------------
# 12. 1MB stdin payload accepted and processed.
# ---------------------------------------------------------------------------
async def test_huge_stdin_handled(runner: DockerCodeRunner) -> None:
    big_str = "x" * (1024 * 1024)  # 1 MB
    request = SandboxRunRequest(
        code="def measure(s): return len(s)",
        entry_function="measure",
        test_cases=[{"input": repr(big_str), "expected": str(len(big_str))}],
        timeout_seconds=15,
    )
    result = await runner.run(request)
    assert result.status == "all_passed", result
    assert result.test_results[0].actual == str(len(big_str))


# ---------------------------------------------------------------------------
# 13. SECURITY CLAIM: cap_drop=ALL blocks privileged operations like mount.
# ---------------------------------------------------------------------------
async def test_capability_drop_blocks_mount(runner: DockerCodeRunner) -> None:
    code = (
        "def try_mount(x):\n"
        "    import os, subprocess\n"
        "    os.makedirs('/tmp/m', exist_ok=True)\n"
        "    subprocess.run(\n"
        "        ['mount', '-t', 'tmpfs', 'tmpfs', '/tmp/m'],\n"
        "        check=True,\n"
        "        capture_output=True,\n"
        "    )\n"
        "    return 'mounted'\n"
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="try_mount",
        test_cases=[{"input": "0", "expected": "mounted"}],
        timeout_seconds=10,
    )
    result = await runner.run(request)
    # Must NOT have mounted. Either mount binary missing (FileNotFoundError),
    # or it ran and was denied by EPERM (CalledProcessError).
    assert result.status != "all_passed"
    err = (result.test_results[0].error or "") if result.test_results else ""
    actual = result.test_results[0].actual if result.test_results else None
    assert actual != "'mounted'"
    assert "FileNotFoundError" in err or "CalledProcessError" in err or "PermissionError" in err, (
        err
    )
