"""CORS preflight + actual-response tests for the FastAPI app.

Validates the CORSMiddleware config in app.main:

- Exact-origin allow list (localhost dev, production Vercel hostname)
- Vercel preview origins matched via allow_origin_regex (one subdomain per PR)
- Unknown origins receive no Access-Control-Allow-Origin header (browser-level
  rejection — Starlette may still 200 the OPTIONS, but absence of ACAO is the
  load-bearing invariant)
- Real responses (not just OPTIONS preflight) carry CORS headers when the
  origin is allowed, so the browser delivers the response body to JS

These tests do NOT depend on Postgres — OPTIONS preflight is short-circuited
by CORSMiddleware before any route handler runs, and /health is a no-DB GET.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

LOCAL_DEV_ORIGIN = "http://localhost:3000"
VERCEL_PREVIEW_ORIGIN = "https://studyverify-git-feature-user.vercel.app"
DISALLOWED_ORIGIN = "https://evil.example.com"


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/solve",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )


def test_cors_preflight_allowed_exact_origin_localhost() -> None:
    client = TestClient(app)
    response = _preflight(client, LOCAL_DEV_ORIGIN)

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == LOCAL_DEV_ORIGIN
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_cors_preflight_allowed_vercel_preview_via_regex() -> None:
    client = TestClient(app)
    response = _preflight(client, VERCEL_PREVIEW_ORIGIN)

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == VERCEL_PREVIEW_ORIGIN


def test_cors_preflight_unknown_origin_has_no_allow_origin_header() -> None:
    client = TestClient(app)
    response = _preflight(client, DISALLOWED_ORIGIN)

    # Browser-level invariant: absence of ACAO blocks the cross-origin response,
    # regardless of the HTTP status code Starlette returns for the preflight.
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_real_response_includes_headers_for_allowed_origin() -> None:
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": LOCAL_DEV_ORIGIN})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == LOCAL_DEV_ORIGIN
