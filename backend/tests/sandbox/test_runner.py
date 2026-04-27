from __future__ import annotations

import sys
import textwrap
import time

import pytest

from app.sandbox.runner import PythonSubprocessRunner
from app.sandbox.schemas import SandboxRunRequest

POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only rlimits")
LINUX_ONLY = pytest.mark.skipif(
    sys.platform != "linux", reason="RLIMIT_AS only enforced on Linux (macOS rejects it)"
)


@pytest.fixture
def runner() -> PythonSubprocessRunner:
    return PythonSubprocessRunner()


async def test_happy_path_all_pass(runner: PythonSubprocessRunner) -> None:
    code = textwrap.dedent(
        """
        def add(a, b):
            return a + b
        """
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="add",
        test_cases=[
            {"input": "(1, 2)", "expected": "3"},
            {"input": "(0, 0)", "expected": "0"},
            {"input": "(-1, 1)", "expected": "0"},
        ],
    )
    result = await runner.run(request)
    assert result.status == "all_passed"
    assert result.pass_count == 3
    assert result.fail_count == 0
    assert all(r.passed for r in result.test_results)


async def test_function_not_defined(runner: PythonSubprocessRunner) -> None:
    code = "def something_else(x): return x"
    request = SandboxRunRequest(
        code=code,
        entry_function="missing_fn",
        test_cases=[{"input": "1", "expected": "1"}],
    )
    result = await runner.run(request)
    assert result.status == "error"
    assert result.test_results == []
    assert "missing_fn" in (result.error or "")


async def test_one_test_raises_others_still_run(runner: PythonSubprocessRunner) -> None:
    code = textwrap.dedent(
        """
        def divide(args):
            a, b = args
            return a // b
        """
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="divide",
        test_cases=[
            {"input": "[10, 2]", "expected": "5"},
            {"input": "[1, 0]", "expected": "anything"},
            {"input": "[9, 3]", "expected": "3"},
        ],
    )
    result = await runner.run(request)
    assert result.status == "some_failed"
    assert len(result.test_results) == 3
    assert result.test_results[0].passed is True
    assert result.test_results[1].passed is False
    assert result.test_results[1].error is not None
    assert "ZeroDivisionError" in result.test_results[1].error
    assert result.test_results[2].passed is True


async def test_wrong_answer_records_actual(runner: PythonSubprocessRunner) -> None:
    code = "def f(x): return x + 1"
    request = SandboxRunRequest(
        code=code,
        entry_function="f",
        test_cases=[{"input": "1", "expected": "999"}],
    )
    result = await runner.run(request)
    assert result.status == "some_failed"
    assert result.test_results[0].passed is False
    assert result.test_results[0].actual == "2"
    assert result.test_results[0].error is None


async def test_multi_arg_via_tuple(runner: PythonSubprocessRunner) -> None:
    code = "def mul(a, b): return a * b"
    request = SandboxRunRequest(
        code=code,
        entry_function="mul",
        test_cases=[{"input": "(2, 3)", "expected": "6"}],
    )
    result = await runner.run(request)
    assert result.status == "all_passed"
    assert result.test_results[0].actual == "6"


async def test_infinite_loop_times_out(runner: PythonSubprocessRunner) -> None:
    code = textwrap.dedent(
        """
        def loop_forever(x):
            while True:
                pass
        """
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="loop_forever",
        test_cases=[{"input": "0", "expected": "0"}],
        timeout_seconds=1,
    )
    start = time.perf_counter()
    result = await runner.run(request)
    elapsed = time.perf_counter() - start
    assert result.status == "timeout"
    assert result.test_results == []
    assert elapsed < 5  # generous wall-clock bound; primary timeout is 1s


@LINUX_ONLY
async def test_memory_bomb_caught(runner: PythonSubprocessRunner) -> None:
    code = textwrap.dedent(
        """
        def hog(x):
            return [0] * (10 ** 9)
        """
    )
    request = SandboxRunRequest(
        code=code,
        entry_function="hog",
        test_cases=[{"input": "0", "expected": "ignored"}],
        memory_mb=32,
        timeout_seconds=3,
    )
    result = await runner.run(request)
    # Either MemoryError captured per-test, or process killed by OS — both acceptable.
    assert result.status != "all_passed"


async def test_user_code_syntax_error(runner: PythonSubprocessRunner) -> None:
    request = SandboxRunRequest(
        code="def broken(:\n    pass",
        entry_function="broken",
        test_cases=[{"input": "1", "expected": "1"}],
    )
    result = await runner.run(request)
    assert result.status == "error"
    assert result.test_results == []
    assert "FATAL" in (result.error or "") or "user code" in (result.error or "")


async def test_str_comparison_fallback(runner: PythonSubprocessRunner) -> None:
    # Wrapper allows either repr-match or str-match. None passes both forms.
    code = "def f(x): return None"
    request = SandboxRunRequest(
        code=code,
        entry_function="f",
        test_cases=[{"input": "0", "expected": "None"}],
    )
    result = await runner.run(request)
    assert result.status == "all_passed"
