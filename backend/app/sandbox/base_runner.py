"""Abstract base class for sandbox runners.

The base class owns runner-agnostic logic: build the JSON payload, dispatch to
the platform-specific isolation primitive, parse the wrapper's JSON output,
and aggregate into SandboxRunResult.

Subclasses own only the isolation primitive (_execute_code):
- PythonSubprocessRunner runs the wrapper in a local subprocess with rlimits.
- DockerCodeRunner runs the wrapper in a hardened container.

The wrapper script is a STATIC constant. User code, the entry function name,
and test cases flow through stdin as a single JSON payload. The wrapper itself
is never templated with user code.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod

from app.sandbox.schemas import (
    SandboxRunRequest,
    SandboxRunResult,
    SandboxStatus,
    TestExecutionResult,
)

logger = logging.getLogger("app.sandbox")

_STDERR_TRUNC = 500
_STDOUT_TRUNC = 500
_FATAL_EXIT_CODE = 2

WRAPPER_SCRIPT = r"""
import ast
import json
import os
import sys
import time

def _main():
    try:
        input_path = os.environ.get("STUDYVERIFY_INPUT_PATH")
        if input_path:
            with open(input_path) as f:
                raw = f.read()
        else:
            raw = sys.stdin.read()
        payload = json.loads(raw)
        user_code = payload["code"]
        entry_function = payload["entry_function"]
        test_cases = payload["test_cases"]
    except Exception as e:
        print(f"FATAL: bad payload: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)

    namespace = {}
    try:
        exec(user_code, namespace)
    except Exception as e:
        print(f"FATAL: user code failed to load: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)

    fn = namespace.get(entry_function)
    if not callable(fn):
        print(f"FATAL: function {entry_function} not defined or not callable", file=sys.stderr)
        sys.exit(2)

    results = []
    for i, tc in enumerate(test_cases):
        start = time.perf_counter()
        try:
            args = ast.literal_eval(tc["input"])
            actual = fn(*args) if isinstance(args, tuple) else fn(args)
            actual_str = repr(actual)
            passed = actual_str == tc["expected"] or str(actual) == tc["expected"]
            results.append({
                "test_index": i,
                "input": tc["input"],
                "expected": tc["expected"],
                "actual": actual_str,
                "passed": passed,
                "error": None,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            })
        except Exception as e:
            results.append({
                "test_index": i,
                "input": tc["input"],
                "expected": tc["expected"],
                "actual": None,
                "passed": False,
                "error": f"{type(e).__name__}: {e}",
                "duration_ms": int((time.perf_counter() - start) * 1000),
            })

    print(json.dumps(results))

_main()
"""


class TestRunner(ABC):
    """Abstract base for sandbox runners.

    Subclasses implement _execute_code (the isolation primitive). The base
    class owns payload construction, dispatch, JSON result parsing, and
    SandboxRunResult aggregation. The wrapper itself iterates test_cases
    inside the isolation boundary; the base class does not loop over them.
    """

    async def run(self, request: SandboxRunRequest) -> SandboxRunResult:
        payload = json.dumps(
            {
                "code": request.code,
                "entry_function": request.entry_function,
                "test_cases": request.test_cases,
            }
        ).encode()

        wall_start = time.perf_counter()
        stdout, stderr, exit_code, timed_out = await self._execute_code(
            code=WRAPPER_SCRIPT,
            payload=payload,
            timeout_seconds=request.timeout_seconds,
            memory_mb=request.memory_mb,
        )
        wall_ms = int((time.perf_counter() - wall_start) * 1000)

        if timed_out:
            logger.info(
                "sandbox.run entry_function=%s n_tests=%d status=timeout wall_ms=%d",
                request.entry_function,
                len(request.test_cases),
                wall_ms,
            )
            return SandboxRunResult(
                status="timeout",
                test_results=[],
                pass_count=0,
                fail_count=0,
                error=f"subprocess exceeded {request.timeout_seconds}s timeout",
            )

        result = self._parse_execution_result(stdout, stderr, exit_code)
        logger.info(
            "sandbox.run entry_function=%s n_tests=%d pass=%d fail=%d status=%s "
            "wall_ms=%d returncode=%d",
            request.entry_function,
            len(request.test_cases),
            result.pass_count,
            result.fail_count,
            result.status,
            wall_ms,
            exit_code,
        )
        return result

    @abstractmethod
    async def _execute_code(
        self,
        code: str,
        payload: bytes,
        timeout_seconds: int,
        memory_mb: int,
    ) -> tuple[bytes, bytes, int, bool]:
        """Run code with payload as stdin.

        Returns (stdout, stderr, exit_code, timed_out).
        """

    @staticmethod
    def _parse_execution_result(stdout: bytes, stderr: bytes, exit_code: int) -> SandboxRunResult:
        stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""
        stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""

        if exit_code == _FATAL_EXIT_CODE:
            return SandboxRunResult(
                status="error",
                test_results=[],
                pass_count=0,
                fail_count=0,
                error=stderr_str[:_STDERR_TRUNC].strip() or "wrapper FATAL",
            )

        if exit_code != 0:
            stderr_snippet = stderr_str[:_STDERR_TRUNC].strip()
            return SandboxRunResult(
                status="error",
                test_results=[],
                pass_count=0,
                fail_count=0,
                error=(
                    f"subprocess exited with code {exit_code}: {stderr_snippet or '(no stderr)'}"
                ),
            )

        try:
            raw_results = json.loads(stdout_str)
        except json.JSONDecodeError:
            stdout_snippet = stdout_str[:_STDOUT_TRUNC]
            return SandboxRunResult(
                status="error",
                test_results=[],
                pass_count=0,
                fail_count=0,
                error=f"failed to parse wrapper stdout as JSON: {stdout_snippet!r}",
            )

        test_results = [TestExecutionResult.model_validate(r) for r in raw_results]
        pass_count = sum(1 for r in test_results if r.passed)
        fail_count = len(test_results) - pass_count
        status: SandboxStatus = "all_passed" if fail_count == 0 and test_results else "some_failed"
        return SandboxRunResult(
            status=status,
            test_results=test_results,
            pass_count=pass_count,
            fail_count=fail_count,
            error=None,
        )
