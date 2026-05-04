# StudyVerify — Step 7: Frontend MVP Spec v2

## Goal

Build a minimal frontend that demonstrates the full StudyVerify loop:
1 problem, code editor, submit -> verify, get hint. Deploy to Vercel.
End-to-end demo URL accessible publicly.

This is the "production demo" milestone: the first step where the
backend becomes visible outside the repo.

## Why This Step

Backend Steps 0-6 are complete: solver persistence, verifier
persistence, hint generation, RAG retrieval, multi-provider LLM gateway,
and anti-leak hardening. None of that is visible without a UI.

LangGraph orchestration was deferred at Step 6.3 specifically to wait
for real UX feedback from a frontend. Step 7 produces that feedback.

## Tech Stack

- Next.js 14.2+ with App Router only
- TypeScript
- Tailwind CSS
- `@monaco-editor/react`
- Native `fetch`
- `useState` and `useEffect` only for MVP state
- Vercel deployment
- Backend deployed on Oracle Cloud

Do not add shadcn/ui, framer-motion, axios, React Query, SWR, Redux,
Zustand, or Context API in Step 7. Anything more is Step 8+ scope.

## Out of Scope

- User authentication / login
- Multiple problems / problem browser
- Submission history persistence
- User progress dashboard
- Dark mode
- Mobile-optimized Monaco experience
- Streaming hint output
- Client-side linting or Python syntax checking beyond Monaco basics
- i18n / multi-language UI
- Analytics / telemetry
- Next.js API routes or a backend-for-frontend proxy

## Repository Decision

Use a new GitHub repo: `studyverify-frontend`.

This is a project decision, not a Vercel limitation. Vercel can deploy a
Next.js app from a monorepo subdirectory by configuring the project root
directory. A separate repo is chosen for this MVP because:

- Frontend and backend deploy independently.
- Frontend tooling is npm/Node while backend tooling is uv/Python.
- Sonnet can work in a smaller repo while the user learns React/Next.js.
- CI/CD, environment variables, and README instructions stay simpler.

Frontend must reference the backend API contract in docs, but must not
import backend Python code.

## Architecture

```text
Browser
   |
   | HTTPS fetch, CORS-enabled
   v
Next.js App Router frontend on Vercel
   - app/page.tsx renders static page shell
   - DemoApp is a Client Component
   - DemoApp useEffect initializes /solve
   - Client handlers call /verify and /hint
   |
   v
Backend on Oracle Cloud
   - POST /api/v1/solve  -> creates solver_session
   - POST /api/v1/verify -> creates verifier_session
   - POST /api/v1/hint   -> creates hint_session
```

No Next.js API routes. No proxy. Direct browser -> backend calls.

## Deployment Prerequisite: HTTPS Backend

Vercel serves the frontend over HTTPS. The browser will block `fetch()`
from an HTTPS page to an HTTP backend as mixed content. Therefore Phase 8
cannot pass unless the Oracle Cloud backend has a public HTTPS URL before
production deployment.

Required before Vercel production acceptance:

- `NEXT_PUBLIC_API_URL` must be an `https://...` URL in Vercel.
- Backend TLS can be provided by a reverse proxy, load balancer, tunnel,
  or domain/CDN layer.
- Production verification must test the deployed Vercel URL in a browser,
  not only server-side curl.

Local development may continue to use:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## File Structure

```text
studyverify-frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── globals.css
│   └── components/
│       ├── ProblemCard.tsx
│       ├── DemoApp.tsx
│       ├── CodeEditor.tsx
│       ├── VerifyButton.tsx
│       ├── TestResultsTable.tsx
│       ├── HintPanel.tsx
│       ├── ErrorBanner.tsx
│       └── LoadingPanel.tsx
├── lib/
│   ├── api.ts
│   ├── mock-api.ts
│   ├── demo-problem.ts
│   └── types.ts
├── tests/
│   └── mvp-smoke.spec.ts
├── public/
│   └── (favicon/icons)
├── .env.local
├── .env.production.example
├── next.config.js
├── package.json
├── playwright.config.ts
├── tsconfig.json
├── tailwind.config.ts
└── README.md
```

Environment files:

```env
# .env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_API_MODE=mock
```

```env
# .env.production.example
NEXT_PUBLIC_API_URL=https://api.studyverify.com
NEXT_PUBLIC_API_MODE=real
```

`NEXT_PUBLIC_API_MODE` values:

- `mock`: use canned frontend-only responses from `lib/mock-api.ts`.
- `real`: use browser `fetch()` against `NEXT_PUBLIC_API_URL`.

Default for local development should be `mock` until Phase 7 real-backend
testing. Default for production must be `real`.

## Page Structure

The MVP is a single page with three visible regions:

```text
Layout:
  - Header: "StudyVerify" + GitHub link

Page:
  - Left: ProblemCard
  - Right: DemoApp
    - CodeEditor
    - Submit button
    - Test results
    - HintPanel
```

`app/page.tsx` remains a Server Component, but it does not call
`/api/v1/solve`. It renders the static shell and passes
`DEMO_PROBLEM` / `DEFAULT_BUGGY_CODE` to the Client Component.

`DemoApp.tsx` owns initialization:

```text
Client mount:
  useEffect -> solveProblem(DEMO_PROBLEM)
    success -> store solver_session_id
    failure -> render ErrorBanner inline

User clicks Submit:
  verifyCode(solver_session_id, code)
    success -> store verifier_session_id + verifier output
    failure -> render ErrorBanner inline

User clicks Get Hint:
  getHint(verifier_session_id)
    success -> append mapped hint
    failure -> render ErrorBanner inline
```

Reason: backend-down is an expected app state for this MVP. If `/solve`
is awaited in `app/page.tsx`, thrown errors during server render can
route to `error.tsx` instead of showing the inline banner described by
the UX spec. Client-side `useEffect` also makes CORS and mixed-content
issues visible during browser testing.

## Backend API Contract

These TypeScript types must match the live backend schemas:

- `POST /api/v1/solve` in `backend/app/api/routes/solver.py`
- `POST /api/v1/verify` in `backend/app/api/routes/verify.py`
- `POST /api/v1/hint` in `backend/app/api/routes/hint.py`
- solver schemas in `backend/app/agents/solver/schemas.py`
- verifier schemas in `backend/app/agents/verifier/schemas.py`
- hint schemas in `backend/app/schemas/hint_session.py`

### `lib/types.ts`

```typescript
export type TestCase = {
  input: string;
  expected: string;
  description: string;
};

export type PlanStep = {
  step_number: number;
  action: string;
  rationale: string;
};

export type SolverTestResult = {
  test_index: number;
  input: string;
  expected: string;
  actual: string | null;
  passed: boolean;
  error: string | null;
  duration_ms: number;
};

export type SolveRequest = {
  problem_id: string;
  problem_text: string;
  test_cases: TestCase[];
};

export type SolveResponse = {
  session_id: string;
  output: {
    problem_id: string;
    entry_function: string;
    analysis: string;
    plan_steps: PlanStep[];
    code: string;
    explanation: string;
    confidence: number;
    verified: boolean;
    test_results: SolverTestResult[];
    retry_used: boolean;
  };
};

export type RedactedTestResult = {
  input: string;
  actual: string | null;
  passed: boolean;
  duration_ms: number | null;
  error: string | null;
};

export type VerifyResponse = {
  session_id: string;
  output: {
    problem_id: string;
    verified: boolean;
    status: "all_passed" | "some_failed" | "error" | "timeout";
    pass_count: number;
    fail_count: number;
    test_results: RedactedTestResult[];
    diagnosis: string;
    sandbox_error: string | null;
  };
};

export type HintResponse = {
  session_id: string; // hint_session_id, not verifier_session_id
  hint_index: number;
  hint_text: string;
};

export type HintViewModel = {
  index: number;
  text: string;
};
```

Important anti-leak invariant:

- `VerifyResponse.output.test_results` must not contain `expected`.
- The UI may show expected outputs in the static `ProblemCard` because
  the MVP problem statement intentionally displays public demo tests.
- The `TestResultsTable` for verifier output must not show an Expected
  column.

## Demo Problem

Use the existing `py-001-sum-list` fixture:

```typescript
// lib/demo-problem.ts
import type { SolveRequest } from "./types";

export const DEMO_PROBLEM: SolveRequest = {
  problem_id: "py-001-sum-list",
  problem_text:
    "Write a Python function `sum_list(nums)` that returns the sum of all integers in the input list. If the list is empty, return 0.",
  test_cases: [
    { input: "[1, 2, 3]", expected: "6", description: "basic" },
    { input: "[]", expected: "0", description: "empty list" },
    { input: "[-1, 1, 0]", expected: "0", description: "negatives + zero" },
  ],
};

export const DEFAULT_BUGGY_CODE = `def sum_list(nums):
    return 0
`;
```

## API Wrapper and Mock Mode

### `lib/api.ts`

`lib/api.ts` is the only public API wrapper used by components. It reads
`NEXT_PUBLIC_API_MODE` and routes to real fetch or mock responses.

```typescript
import { solveProblemMock, verifyCodeMock, getHintMock } from "./mock-api";
import type { HintResponse, SolveRequest, SolveResponse, VerifyResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_MODE = process.env.NEXT_PUBLIC_API_MODE || "mock";

function isMockMode() {
  return API_MODE === "mock";
}

export async function solveProblem(problem: SolveRequest): Promise<SolveResponse> {
  if (isMockMode()) return solveProblemMock(problem);

  const res = await fetch(`${API_BASE}/api/v1/solve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(problem),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Solve failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function verifyCode(
  solverSessionId: string,
  studentCode: string
): Promise<VerifyResponse> {
  if (isMockMode()) return verifyCodeMock(solverSessionId, studentCode);

  const res = await fetch(`${API_BASE}/api/v1/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      solver_session_id: solverSessionId,
      student_code: studentCode,
    }),
  });

  if (!res.ok) {
    throw new Error(`Verify failed: ${res.status}`);
  }
  return res.json();
}

export async function getHint(verifierSessionId: string): Promise<HintResponse> {
  if (isMockMode()) return getHintMock(verifierSessionId);

  const res = await fetch(`${API_BASE}/api/v1/hint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ verifier_session_id: verifierSessionId }),
  });

  if (!res.ok) {
    throw new Error(`Hint failed: ${res.status}`);
  }
  return res.json();
}
```

### `lib/mock-api.ts`

Mock mode is for frontend development only. Canned data must look
realistic enough for UI work, but clearly fake so nobody mistakes it for
backend validation.

Mock behavior:

- `solveProblemMock()` returns a fake solver session ID and a correct
  reference-style `output.code`.
- `verifyCodeMock()` treats code containing `return sum(nums)` as passed.
- Any other code returns a failed verifier response.
- `getHintMock()` returns up to five fake hints, incrementing per browser
  session.
- Hint cap is 5 to match backend `MAX_HINTS_PER_VERIFIER_SESSION`.

Mock canned data shape:

```typescript
const MOCK_SOLVER_SESSION_ID = "00000000-0000-4000-8000-000000000001";

const MOCK_DIAGNOSIS =
  "[mock] Your function currently returns a constant value, so it does not react to the numbers inside nums.";

const MOCK_HINTS = [
  "[mock] Try asking what information from nums your function is currently ignoring.",
  "[mock] A running total usually starts from the value that represents nothing accumulated yet.",
  "[mock] Think about how each number in the list should affect that running total.",
  "[mock] Empty input should naturally fall out of your starting value.",
  "[mock] Before returning, check whether every element had a chance to update the result.",
];
```

The mock failed verifier response must omit `expected`:

```typescript
test_results: [
  { input: "[1, 2, 3]", actual: "0", passed: false, duration_ms: 2, error: null },
  { input: "[]", actual: "0", passed: true, duration_ms: 1, error: null },
  { input: "[-1, 1, 0]", actual: "0", passed: true, duration_ms: 1, error: null },
]
```

## Backend CORS Change

This is a separate backend commit and must happen before frontend Phase 4
real-backend integration. Do not bundle it into the frontend repo commit.

### Backend settings

Add settings in `backend/app/core/config.py`:

```python
CORS_ALLOWED_ORIGINS: str = (
    "http://localhost:3000,"
    "https://studyverify.vercel.app"
)
CORS_ALLOW_ORIGIN_REGEX: str = r"https://[a-zA-Z0-9-]+\.vercel\.app"
```

Add to `.env.docker.example`:

```env
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://studyverify.vercel.app
CORS_ALLOW_ORIGIN_REGEX=https://[a-zA-Z0-9-]+\.vercel\.app
```

### Backend middleware

FastAPI's `CORSMiddleware` uses Starlette. `allow_origins` is an exact
origin list, except for the special `"*"` value. It does not treat
`"https://*.vercel.app"` as a wildcard subdomain. Vercel preview URLs
must use `allow_origin_regex`.

Add to `backend/app/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_split_csv(settings.CORS_ALLOWED_ORIGINS),
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
```

The exact placement should be immediately after app creation and before
the route includes, keeping `main.py` as the app composition owner.

### Backend tests for CORS

Add backend tests before Phase 4 starts:

- `OPTIONS /api/v1/solve` with origin `http://localhost:3000` succeeds.
- `OPTIONS /api/v1/solve` with origin
  `https://studyverify-git-feature-user.vercel.app` succeeds by regex.
- `OPTIONS /api/v1/solve` with origin `https://evil.example.com` does
  not return `access-control-allow-origin`.
- A real backend error response still includes CORS headers for allowed
  origins where feasible.

## Component Specs

### `app/layout.tsx`

Server Component.

- `<html lang="en">`
- Body classes: `bg-gray-50 min-h-screen text-gray-900`
- Header:
  - `h-14 bg-white border-b`
  - `max-w-6xl mx-auto px-4 flex items-center justify-between`
  - Left: `StudyVerify`
  - Right: GitHub link
- Main content renders `{children}`.
- Footer optional, short, and unobtrusive.

### `app/page.tsx`

Server Component.

- Does not call backend.
- Imports `DEMO_PROBLEM` and `DEFAULT_BUGGY_CODE`.
- Renders:

```tsx
<main className="max-w-6xl mx-auto p-4">
  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <ProblemCard problem={DEMO_PROBLEM} />
    <DemoApp problem={DEMO_PROBLEM} initialCode={DEFAULT_BUGGY_CODE} />
  </div>
</main>
```

### `ProblemCard.tsx`

Server Component.

- Pure display; no state.
- Props: `{ problem: SolveRequest }`
- Shows:
  - Problem text
  - Static public demo test cases
  - Input and expected output for those public demo tests
- This component may show expected outputs because these are part of the
  hardcoded demo problem, not verifier response data.

### `DemoApp.tsx`

Client Component.

State:

```typescript
const [code, setCode] = useState(initialCode);
const [solverSessionId, setSolverSessionId] = useState<string | null>(null);
const [verifierSessionId, setVerifierSessionId] = useState<string | null>(null);
const [verifyOutput, setVerifyOutput] = useState<VerifyResponse["output"] | null>(null);
const [hints, setHints] = useState<HintViewModel[]>([]);
const [loading, setLoading] = useState({ solve: true, verify: false, hint: false });
const [error, setError] = useState<string | null>(null);
```

Initialization:

```typescript
useEffect(() => {
  let cancelled = false;

  async function init() {
    try {
      setLoading((current) => ({ ...current, solve: true }));
      const response = await solveProblem(problem);
      if (!cancelled) setSolverSessionId(response.session_id);
    } catch (err) {
      if (!cancelled) setError("Backend is unavailable. Try mock mode or restart the API.");
    } finally {
      if (!cancelled) setLoading((current) => ({ ...current, solve: false }));
    }
  }

  init();
  return () => {
    cancelled = true;
  };
}, [problem]);
```

Handlers:

- `handleCodeChange(newCode)` updates `code`.
- `handleVerify()`:
  - Blocks empty code.
  - Blocks if `solverSessionId` is missing.
  - Calls `verifyCode(solverSessionId, code)`.
  - Stores `response.session_id` as `verifierSessionId`.
  - Stores `response.output`.
  - Clears prior hints because a new verifier session has a new hint chain.
- `handleGetHint()`:
  - Blocks if `verifierSessionId` is missing.
  - Blocks if `hints.length >= 5`.
  - Calls `getHint(verifierSessionId)`.
  - Explicitly maps API response:

```typescript
setHints((current) => [
  ...current,
  { index: response.hint_index, text: response.hint_text },
]);
```

Renders:

- `LoadingPanel` while initial `/solve` is pending.
- Inline `ErrorBanner` if initial `/solve` fails.
- `CodeEditor`
- `VerifyButton`
- `TestResultsTable` after verify
- `HintPanel`
- Dismissible `ErrorBanner` for verify/hint errors

### `CodeEditor.tsx`

Client Component.

Use `next/dynamic` inside the Client Component:

```typescript
"use client";

import dynamic from "next/dynamic";

const Monaco = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <div className="h-[400px] bg-gray-100" />,
});
```

`ssr: false` is supported for dynamically importing Client Components in
Next.js App Router. Do not put this dynamic import in a Server Component.

Props:

```typescript
type Props = {
  code: string;
  onChange: (newCode: string) => void;
};
```

Editor config:

```tsx
<Monaco
  height="400px"
  defaultLanguage="python"
  value={code}
  onChange={(value) => onChange(value || "")}
  options={{
    minimap: { enabled: false },
    fontSize: 14,
    scrollBeyondLastLine: false,
    wordWrap: "on",
  }}
/>
```

### `VerifyButton.tsx`

Client Component.

Props:

```typescript
{
  onClick: () => void;
  loading: boolean;
  disabled?: boolean;
}
```

Disable if:

- initial solve is still loading
- no `solverSessionId`
- verify call is loading
- code is empty

### `TestResultsTable.tsx`

Client Component.

Props:

```typescript
{ output: VerifyResponse["output"] }
```

Render:

- Summary:
  - if `output.verified`: "All tests passed"
  - else: "Verification failed"
- Show `output.diagnosis` when present.
- Show `output.sandbox_error` as an error banner when present.
- Table columns:
  - Status
  - Input
  - Actual

Do not show an Expected column. Verifier output intentionally omits
expected outputs.

### `HintPanel.tsx`

Client Component.

Props:

```typescript
{
  hints: HintViewModel[];
  onGetHint: () => void;
  loading: boolean;
  maxReached: boolean; // hints.length >= 5
  disabled: boolean;   // verifierSessionId is null
}
```

Render:

- Header: `Hints ({hints.length}/5)`
- Button:
  - hidden or disabled when `maxReached`
  - disabled while loading or before a verifier session exists
  - text: `Get a Hint` or `Get Hint #${hints.length + 1}`
- Hints list:
  - `Hint {hint.index}`
  - `hint.text`
- Max message:
  - "You've used all 5 hints. Try revising your code and submitting again."

### `ErrorBanner.tsx`

Client Component.

Props:

```typescript
{
  message: string;
  onDismiss?: () => void;
}
```

Use for expected frontend-visible failures:

- backend unavailable
- CORS blocked
- mixed-content blocked
- `/solve`, `/verify`, or `/hint` returns non-OK
- empty code submit

### `LoadingPanel.tsx`

Client Component or plain component.

Minimal loading UI while `solveProblem()` initializes:

- "Preparing demo session..."
- Do not show as a marketing hero.
- Keep layout stable so Monaco/results do not jump.

## Solver Session Lifecycle

Step 7 creates one `solver_session` per page mount. Reloading the page
creates a new solver row. Any verifier/hint rows from the previous page
load remain linked to their original solver session through the database
FK chain; they are not orphaned.

This is acceptable for MVP because:

- There is no login or durable frontend state.
- Reload is a clean demo reset.
- Solver/verifier/hint session history is backend-owned data.

Known risk:

- Dev/staging demo usage can create many similar failed verifier rows.
- Existing retrieval corpus filters such as `verified=false` and
  `embedding_status=success` exclude many irrelevant rows, but if demo
  failures are embedded successfully they can still surface in retrieval.

Documented Step 7 closure backlog:

- If demo usage accumulates retrieval noise, filter retrieval by
  `created_at` or add a `demo_tag` / source column before seeding or
  retrieving from demo sessions.

## Phase Breakdown

### Phase 0: Backend CORS Commit

This phase happens in the backend repo before frontend real-backend
integration.

- Add `CORS_ALLOWED_ORIGINS`.
- Add `CORS_ALLOW_ORIGIN_REGEX`.
- Add `CORSMiddleware` in `backend/app/main.py`.
- Use exact `allow_origins` plus regex for Vercel preview URLs.
- Add backend CORS tests.
- Rebuild/redeploy backend.

Acceptance:

- Localhost origin works.
- Production Vercel origin works.
- Vercel preview origin works by regex.
- Unknown origin is rejected.

### Phase 1: Project Initialization

- `npx create-next-app@latest studyverify-frontend`
  - TypeScript: yes
  - ESLint: yes
  - Tailwind: yes
  - `src/` directory: no
  - App Router: yes
  - import alias: default `@/*` is fine
- Verify Node version supports Next.js 14.
- Check whether `studyverify-frontend` already exists before creating.
- Start dev server on `localhost:3000`.
- Verify Tailwind works.
- Initialize git and push to new GitHub repo.

### Phase 2: Static Layout + ProblemCard

- Implement `app/layout.tsx`.
- Create `lib/types.ts`.
- Create `lib/demo-problem.ts`.
- Create `ProblemCard.tsx`.
- Update `app/page.tsx` to render static shell.
- Verify problem and public test cases display correctly.

### Phase 3: Monaco Editor

- `npm install @monaco-editor/react`
- Create `CodeEditor.tsx`.
- Use `dynamic(..., { ssr: false })` inside the Client Component.
- Verify editor loads, Python highlighting appears, and typing works.

### Phase 4: Mock API Mode

- Create `lib/mock-api.ts`.
- Create `lib/api.ts`.
- Add `NEXT_PUBLIC_API_MODE=mock` to `.env.local`.
- Implement fake `/solve`, `/verify`, and `/hint` behavior.
- Build `DemoApp` initial `useEffect` using `solveProblem()`.
- Verify the full UI flow works without backend or LLM calls.

### Phase 5: Verify Integration UI

- Implement `VerifyButton`.
- Implement `TestResultsTable`.
- Wire `handleVerify()`.
- Confirm failed mock response shows diagnosis and Status/Input/Actual.
- Confirm passed mock response works when code contains `return sum(nums)`.
- Confirm no Expected column is rendered from verifier output.

### Phase 6: Hint Integration UI

- Implement `HintPanel`.
- Wire `handleGetHint()`.
- Explicitly map `hint_index` / `hint_text` to `HintViewModel`.
- Use 5-hint cap.
- Clear hints when a new verify call creates a new verifier session.
- Verify five hints append; sixth hint is blocked.

### Phase 7: Real Backend Local Integration

- Switch `.env.local` to:

```env
NEXT_PUBLIC_API_MODE=real
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- Run backend locally.
- Verify browser network calls:
  - `POST /api/v1/solve`
  - `POST /api/v1/verify`
  - `POST /api/v1/hint`
- Confirm CORS works from `http://localhost:3000`.
- Confirm backend-down renders inline `ErrorBanner`.
- Confirm real verifier output still renders without `expected`.

### Phase 8: Vercel Deployment

- Confirm Oracle backend has HTTPS URL.
- Set Vercel environment:

```env
NEXT_PUBLIC_API_MODE=real
NEXT_PUBLIC_API_URL=https://<public-backend-host>
```

- Import `studyverify-frontend` repo into Vercel.
- Deploy production.
- Test from `https://studyverify.vercel.app`.
- Confirm no mixed-content errors in browser console.
- Confirm full flow works on the deployed URL.
- Update README with demo URL and screenshot/GIF.

### Phase 9: Playwright Smoke Test

Add one smoke test, not a broad frontend test suite.

Purpose:

- Catch broken app boot.
- Catch missing Monaco/editor shell.
- Catch mock full-flow regressions.

Use mock mode for smoke test by default so it does not spend LLM calls.

Minimum Playwright path:

- Start Next.js dev server with `NEXT_PUBLIC_API_MODE=mock`.
- Visit `/`.
- Assert problem text appears.
- Assert editor container appears.
- Click Submit.
- Assert mock diagnosis appears.
- Click Get Hint.
- Assert `[mock]` hint text appears.

Do not add unit tests in Step 7 unless implementation becomes more
complex than this spec.

## Verification Checklist

Final acceptance criteria:

1. Production URL loads without console errors.
2. Page displays `sum_list` problem and public test cases.
3. Monaco editor loads and default code is prefilled.
4. Initial `/solve` happens in `DemoApp` client `useEffect`.
5. Backend down renders inline `ErrorBanner`; page shell does not crash.
6. Submit calls `/verify` in real mode.
7. Buggy code shows diagnosis and per-test Status/Input/Actual.
8. Correct code shows all tests passed.
9. Verifier UI never renders `expected` from verifier response.
10. Get Hint calls `/hint` in real mode.
11. Hints append as Hint 1 through Hint 5.
12. Sixth hint is blocked or hidden.
13. Empty code submit is blocked with a message.
14. Mock mode works without backend or LLM calls.
15. Real local backend mode works from `localhost:3000`.
16. Vercel production uses HTTPS backend URL.
17. Backend CORS supports exact production origin and Vercel preview regex.
18. Playwright smoke test passes in mock mode.
19. Mobile view stacks vertically and remains readable.
20. README has demo URL and screenshot/GIF.

## What NOT to Do

- Do not call `/solve` from `app/page.tsx`.
- Do not add Next.js API routes or a proxy layer.
- Do not persist code or progress in local storage.
- Do not add login/signup/users.
- Do not add multiple problems.
- Do not add React Query, SWR, Redux, Zustand, or Context API.
- Do not add Server Actions.
- Do not add streaming output.
- Do not show verifier `expected` outputs in `TestResultsTable`.
- Do not rely on `https://*.vercel.app` inside `allow_origins`.
- Do not run repeated real `/solve` calls during layout/UI debugging.
- Do not include demo verifier sessions in the retrieval corpus by
  default. If dev/staging demo failures accumulate and become retrieval
  noise, handle it in the Step 7 closure backlog with a `created_at`
  retrieval filter or a demo/source tag.
- Do not treat Playwright as a full test suite in Step 7; one smoke test
  is enough.

## Critical Pre-implementation Reads for Sonnet

Before coding, Sonnet must read:

1. `backend/app/main.py`
2. `backend/app/api/routes/solver.py`
3. `backend/app/api/routes/verify.py`
4. `backend/app/api/routes/hint.py`
5. `backend/app/agents/solver/schemas.py`
6. `backend/app/agents/verifier/schemas.py`
7. `backend/app/schemas/hint_session.py`
8. `backend/app/services/hint_service.py`

Sonnet must verify these exact contracts before writing TypeScript:

- `SolveResponse.output.code`, not `final_code`.
- `VerifyResponse.output.test_results` uses `RedactedTestResult` and
  omits `expected`.
- `HintResponse` is `{ session_id, hint_index, hint_text }`.
- Backend hint cap is 5.

## Step 7 Closure Backlog

Items deferred unless they block the MVP:

- Mobile-optimized Monaco.
- Streaming hints.
- Code formatting on paste.
- Backend health check display in the UI.
- Loading skeleton polish.
- Broader Playwright real-backend E2E coverage.
- Retrieval-noise guard for demo sessions:
  - filter retrieval by `created_at`, or
  - add a `demo_tag` / source column, or
  - exclude known public-demo sessions from corpus seeding.

## Estimated Time

- Phase 0: 1 hour
- Phase 1: 1 hour
- Phase 2: 1 hour
- Phase 3: 1.5 hours
- Phase 4: 2 hours
- Phase 5: 2 hours
- Phase 6: 2 hours
- Phase 7: 1.5 hours
- Phase 8: 1 hour
- Phase 9: 1 hour

Total: about 14 hours. Calendar: 1.5-2 weeks while learning
React/Next.js in parallel.

## Why This Scope Is Honest

This is a demonstrably full-stack MVP, not a polished product:

- One page.
- One problem.
- No users.
- Mock mode for cheap frontend development.
- Real backend mode for production demo.
- The depth remains in the backend; the frontend is the showcase window.

Resume claim after this step:

> Full-stack AI tutor demo with retrieval-augmented hint generation,
> FastAPI backend, Next.js frontend, Monaco editor, and Vercel deployment.
