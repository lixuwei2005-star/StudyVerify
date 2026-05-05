from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.solver.schemas import TestCase
from app.dependencies import get_test_case_generator_service
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.services.test_case_generator import (
    TestCaseGeneratorError,
    TestCaseGeneratorService,
)

logger = logging.getLogger("app.api.generate_test_cases")

# main.py owns the /api/v1 prefix — do not duplicate it here.
router = APIRouter(tags=["generate_test_cases"])


class GenerateTestCasesRequest(BaseModel):
    problem_text: str = Field(..., min_length=10, max_length=2000)
    entry_function: str = Field(..., pattern=r"^[a-z_][a-z0-9_]*$")
    n: int = Field(default=5, ge=1, le=10)


class GenerateTestCasesResponse(BaseModel):
    test_cases: list[TestCase]


@router.post("/generate-test-cases", response_model=GenerateTestCasesResponse)
async def generate_test_cases(
    request: GenerateTestCasesRequest,
    service: TestCaseGeneratorService = Depends(get_test_case_generator_service),
) -> GenerateTestCasesResponse:
    try:
        cases = await service.generate(
            problem_text=request.problem_text,
            entry_function=request.entry_function,
            n=request.n,
        )
    except LLMTimeoutError as exc:
        logger.warning("generate_test_cases.timeout entry_function=%s err=%s", request.entry_function, exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM provider timed out",
        ) from exc
    except (LLMError, TestCaseGeneratorError) as exc:
        logger.error(
            "generate_test_cases.failed entry_function=%s err=%s",
            request.entry_function,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Generation failed: {exc}",
        ) from exc

    return GenerateTestCasesResponse(test_cases=list(cases))
