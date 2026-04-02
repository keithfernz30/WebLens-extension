from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from hashlib import sha256
from pathlib import Path
import re
from threading import Lock
from typing import Any, Deque, Dict, Optional
import json
import os
import sys
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
try:
    from google import genai
except Exception:  # pragma: no cover - optional dependency at runtime
    genai = None
from pydantic import BaseModel, Field

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

load_dotenv(override=True)

MAX_CONTENT_CHARS = int(os.getenv("WEBLENS_MAX_CONTENT_CHARS", "6000"))
MODEL_TIMEOUT_SEC = int(os.getenv("WEBLENS_MODEL_TIMEOUT_SEC", "20"))
AI_PROVIDER = os.getenv("WEBLENS_AI_PROVIDER", "gemini").strip().lower()
GEMINI_MODEL = os.getenv("WEBLENS_GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = os.getenv("WEBLENS_OPENAI_MODEL", "gpt-4o-mini")

RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_PER_WINDOW = int(os.getenv("WEBLENS_RATE_LIMIT_PER_MIN", "30"))
CACHE_TTL_SEC = int(os.getenv("WEBLENS_CACHE_TTL_SEC", "300"))
CACHE_MAX_ITEMS = int(os.getenv("WEBLENS_CACHE_MAX_ITEMS", "200"))
OUTPUT_SCHEMA_VERSION = "v3"

# In-memory rate limiter (keyed by client IP)
_rate_limit_store: Dict[str, Deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()
_model_executor = ThreadPoolExecutor(max_workers=4)
_result_cache: Dict[str, Dict[str, Any]] = {}
_result_cache_lock = Lock()

app = FastAPI(title="WebLens Backend", version="1.1")
SUPPORTED_MODES = {
    "summarize",
    "explain",
    "extract",
    "translate",
    "quiz",
    "action_items",
    "fact_check",
}


class PageRequest(BaseModel):
    mode: str
    task: str = ""
    language: str = "Hindi"
    detail: str = "short"
    content: str


class PageResponse(BaseModel):
    result: str
    request_id: str


class VisualRequest(BaseModel):
    input_path: str = Field(..., description="Absolute or relative path to image/video")
    model: str = "yolov8n.pt"
    conf: float = 0.25
    frame_step: int = 10


class VisualResponse(BaseModel):
    result: Dict
    request_id: str


def _reload_env() -> None:
    # Keep env in sync with local edits during development.
    load_dotenv(override=True)


def _sanitize_key(raw: Optional[str]) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().strip('"').strip("'")
    return cleaned.replace("\n", "").replace("\r", "").strip()


def _masked_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _get_env_provider() -> str:
    return os.getenv("WEBLENS_AI_PROVIDER", AI_PROVIDER).strip().lower()


def get_client():
    _reload_env()
    provider = _get_env_provider()

    if provider == "gemini":
        if genai is None:
            raise RuntimeError("google-genai package is not installed. Run: pip install google-genai")
        api_key = _sanitize_key(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        if not api_key.startswith("AIza"):
            raise RuntimeError("Invalid Gemini API key format. It should start with 'AIza'.")
        return genai.Client(api_key=api_key, http_options={"api_version": "v1"})

    if provider == "openai":
        if OpenAI is None:
            raise RuntimeError("openai package is not installed. Run: pip install openai")
        api_key = _sanitize_key(os.getenv("OPENAI_API_KEY"))
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        return OpenAI(api_key=api_key)

    raise RuntimeError(f"Unsupported AI provider: {provider}")


def _extract_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def _generate_with_timeout(client, model: str, contents: str):
    future = _model_executor.submit(
        _call_model,
        client,
        model,
        contents,
    )
    try:
        return future.result(timeout=MODEL_TIMEOUT_SEC)
    except FutureTimeoutError:
        future.cancel()
        raise HTTPException(
            status_code=504,
            detail=f"Model timeout after {MODEL_TIMEOUT_SEC}s. Try again with a shorter page.",
        )


def _call_model(client, model: str, contents: str) -> str:
    provider = _get_env_provider()
    if provider == "gemini":
        response = client.models.generate_content(model=model, contents=contents)
        return (response.text or "").strip()

    if provider == "openai":
        response = client.responses.create(model=model, input=contents)
        return (response.output_text or "").strip()

    raise RuntimeError(f"Unsupported AI provider: {provider}")


def _active_model_name() -> str:
    if _get_env_provider() == "openai":
        return OPENAI_MODEL
    return GEMINI_MODEL


def _cache_key(mode: str, task: str, content: str) -> str:
    fingerprint = sha256(content.encode("utf-8")).hexdigest()
    return f"{OUTPUT_SCHEMA_VERSION}|{mode}|{task.strip()}|{fingerprint}"


def _cache_get(key: str) -> Optional[str]:
    now = time.time()
    with _result_cache_lock:
        payload = _result_cache.get(key)
        if not payload:
            return None
        if now - payload["ts"] > CACHE_TTL_SEC:
            _result_cache.pop(key, None)
            return None
        return payload["value"]


def _cache_put(key: str, value: str) -> None:
    with _result_cache_lock:
        if len(_result_cache) >= CACHE_MAX_ITEMS:
            oldest_key = min(_result_cache.items(), key=lambda i: i[1]["ts"])[0]
            _result_cache.pop(oldest_key, None)
        _result_cache[key] = {"ts": time.time(), "value": value}


def _build_base_instruction() -> str:
    return (
        "You are WebLens, an AI page intelligence system. "
        "Be accurate, concise, and structured. "
        "When uncertain, explicitly say what is uncertain."
    )


def _normalize_mode(mode: str) -> str:
    return (mode or "").strip().lower()


def _normalize_detail(detail: str) -> str:
    normalized = (detail or "").strip().lower()
    return "detailed" if normalized == "detailed" else "short"


def _normalize_language(language: str) -> str:
    normalized = (language or "").strip()
    return normalized or "Hindi"


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+", text.strip())
    return [c.strip() for c in chunks if c and c.strip()]


def _target_counts(detail: str) -> Dict[str, int]:
    if detail == "detailed":
        return {"summary": 7, "quiz": 7, "fact_check": 6}
    return {"summary": 3, "quiz": 3, "fact_check": 3}


def _pad_items(items: list[str], source: str, target: int) -> list[str]:
    cleaned = [i.strip() for i in items if i and i.strip()]
    pool = _sentences(source)
    idx = 0
    while len(cleaned) < target and idx < len(pool):
        candidate = pool[idx]
        idx += 1
        if candidate not in cleaned:
            cleaned.append(candidate)
    return cleaned[:target]


def _local_mode_fallback(
    mode: str,
    task: str,
    content: str,
    reason: str = "",
    language: str = "Hindi",
    detail: str = "short",
) -> str:
    sents = _sentences(content)
    top = sents[:5] if sents else [content[:300]]
    title = top[0][:80] if top else "Untitled"
    counts = _target_counts(detail)
    target_summary = counts["summary"]
    target_quiz = counts["quiz"]
    target_fact = counts["fact_check"]

    if mode == "summarize":
        bullets = "\n".join([f"- {s}" for s in _pad_items(top, content, target_summary)])
        return f"Summary:\n{bullets}"

    if mode == "explain":
        core = " ".join(top[:3])
        return f"Simple explanation (local fallback):\n{core}"

    if mode == "extract":
        payload = {
            "title": title,
            "summary": " ".join(top[:2]),
            "key_points": top[:4],
            "entities": [],
        }
        return json.dumps(payload, indent=2)

    if mode == "translate":
        suffix = f" Reason: {reason}" if reason else ""
        return f"Translate mode requires model access for {language}. Local fallback cannot translate reliably.{suffix}"

    if mode == "quiz":
        basis = _pad_items(top, content, target_quiz)
        questions = []
        for i, sentence in enumerate(basis, start=1):
            questions.append(
                f"Q{i}: What is the key idea in: \"{sentence[:90]}\"?\nA{i}: {sentence[:120]}"
            )
        return "Quiz:\n" + ("\n".join(questions) if questions else "No quiz data available.")

    if mode == "action_items":
        actions = [f"{i}. Review: {s[:110]}" for i, s in enumerate(top[:5], start=1)]
        return "Action items (local fallback):\n" + ("\n".join(actions) if actions else "No clear actions found.")

    if mode == "fact_check":
        claims = []
        for i, sentence in enumerate(_pad_items(top, content, target_fact), start=1):
            claims.append(
                f"Claim {i}: {sentence[:120]}\n"
                f"Status {i}: Needs verification\n"
                f"Confidence {i}: Low\n"
                f"Evidence {i}: Trusted primary sources"
            )
        return "Fact Check:\n" + ("\n".join(claims) if claims else "No claims detected.")

    return "Unsupported mode."


def _to_bullets(text: str, max_items: int = 5) -> list[str]:
    lines = [ln.strip("-• \t") for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2:
        return lines[:max_items]
    return _sentences(text)[:max_items]


def _format_mode_output(
    mode: str,
    raw: str,
    source_content: str,
    task: str,
    language: str = "Hindi",
    detail: str = "short",
) -> str:
    if not raw or not raw.strip():
        return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)

    counts = _target_counts(detail)
    if mode == "summarize":
        bullets = _to_bullets(raw, max_items=12)
        if not bullets:
            return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)
        normalized = _pad_items(bullets, source_content, counts["summary"])
        if detail == "short":
            concise = [re.sub(r"\s+", " ", b).strip()[:120] for b in normalized[:3]]
            return "TL;DR Summary:\n" + "\n".join([f"- {b}" for b in concise])
        detailed = [re.sub(r"\s+", " ", b).strip()[:200] for b in normalized[:7]]
        return (
            "Detailed Summary:\n"
            "Overview:\n"
            f"- {detailed[0]}\n"
            f"- {detailed[1] if len(detailed) > 1 else detailed[0]}\n"
            "Key Details:\n"
            + "\n".join([f"- {d}" for d in detailed[2:6]])
            + "\nTakeaway:\n"
            + f"- {detailed[6] if len(detailed) > 6 else detailed[-1]}"
        )

    if mode == "explain":
        body = " ".join(_sentences(raw)[:4]) or raw.strip()
        return f"Simple Explanation:\n{body}"

    if mode == "extract":
        # Handled separately with strict JSON parsing path.
        return raw.strip()

    if mode == "translate":
        # Keep translation plain text with no wrappers when model provides it.
        return raw.strip()

    if mode == "quiz":
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        has_q = any(ln.strip().lower().startswith("q") or "?" in ln for ln in lines)
        if not has_q:
            return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)
        q_lines = [ln.strip() for ln in lines if re.match(r"^Q\d+:", ln.strip(), re.IGNORECASE)]
        a_lines = [ln.strip() for ln in lines if re.match(r"^A\d+:", ln.strip(), re.IGNORECASE)]
        target = counts["quiz"]
        if len(q_lines) < target or len(a_lines) < target:
            return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)
        if detail == "short":
            merged = []
            for i in range(target):
                merged.append(q_lines[i])
                merged.append(a_lines[i])
            return "Quick Quiz:\n" + "\n".join(merged)
        merged = []
        for i in range(target):
            merged.append(q_lines[i])
            merged.append(a_lines[i])
            merged.append(f"Why {i+1}: This tests a key concept from the article.")
        return "Deep Quiz:\n" + "\n".join(merged)

    if mode == "action_items":
        actions = _to_bullets(raw, max_items=8)
        if not actions:
            return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)
        return "Action Items:\n" + "\n".join([f"{i}. {a}" for i, a in enumerate(actions, start=1)])

    if mode == "fact_check":
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)
        target = counts["fact_check"]
        claim_lines = [ln for ln in lines if re.match(r"^Claim\s+\d+:", ln, re.IGNORECASE)]
        if len(claim_lines) < target:
            return _local_mode_fallback(mode, task, source_content, language=language, detail=detail)
        rebuilt = []
        for i in range(1, target + 1):
            claim = next((ln for ln in lines if re.match(rf"^Claim\s+{i}:", ln, re.IGNORECASE)), f"Claim {i}:")
            status = next((ln for ln in lines if re.match(rf"^Status\s+{i}:", ln, re.IGNORECASE)), f"Status {i}: Unclear")
            confidence = next((ln for ln in lines if re.match(rf"^Confidence\s+{i}:", ln, re.IGNORECASE)), f"Confidence {i}: Low")
            evidence = next((ln for ln in lines if re.match(rf"^Evidence\s+{i}:", ln, re.IGNORECASE)), f"Evidence {i}: Verify with trusted sources")
            if detail == "short":
                rebuilt.extend([claim, status])
            else:
                rebuilt.extend([claim, status, confidence, evidence, f"Next Step {i}: Cross-check with a primary source."])
        return ("Quick Fact Check:\n" if detail == "short" else "Detailed Fact Check:\n") + "\n".join(rebuilt)

    return raw.strip()


def _friendly_model_reason(exc: Exception) -> str:
    text = str(exc or "").strip()
    lower = text.lower()

    if "resource_exhausted" in lower or ("429" in lower and "quota" in lower):
        return (
            "Gemini quota exceeded (429 RESOURCE_EXHAUSTED). "
            "Upgrade billing or wait for quota reset, then retry."
        )
    if "api key not valid" in lower or "invalid_argument" in lower:
        return "Invalid Gemini API key. Update GEMINI_API_KEY in weblens-backend/.env and restart backend."
    if "invalid gemini api key format" in lower:
        return "Invalid Gemini API key format. Use the full key from Google AI Studio."
    if "gemini_api_key not set" in lower:
        return "GEMINI_API_KEY is missing. Add it to weblens-backend/.env and restart backend."
    if "openai_api_key not set" in lower:
        return "OPENAI_API_KEY is missing. Add it to environment and restart backend."
    if "unsupported ai provider" in lower:
        return "Unsupported WEBLENS_AI_PROVIDER. Use 'gemini' or 'openai'."
    if "nodename nor servname provided" in lower or "failed to fetch" in lower:
        return "Network/DNS issue while contacting model provider."
    if "timeout" in lower:
        return f"Model request timed out after {MODEL_TIMEOUT_SEC}s."

    return text or "Unknown model error."


def build_prompt(mode: str, task: str, content: str, language: str, detail: str) -> str:
    base_instruction = _build_base_instruction()
    detail_line = "detailed" if detail == "detailed" else "short"
    counts = _target_counts(detail)
    summary_count = str(counts["summary"])
    quiz_count = str(counts["quiz"])
    fact_claim_count = str(counts["fact_check"])

    if mode == "summarize":
        return f"""
{base_instruction}

Create a {detail_line} summary of the following webpage content.
Return EXACTLY {summary_count} bullet points.
STRICT OUTPUT TEMPLATE:
Summary:
- ...
- ...

{content}
"""

    if mode == "explain":
        return f"""
{base_instruction}

Explain the following content in simple terms for a beginner.
Use 1 short paragraph.

{content}
"""

    if mode == "extract":
        return f"""
{base_instruction}

Extract structured information from this webpage.
Return STRICT JSON with this exact structure:

{{
  "title": "string",
  "summary": "short paragraph",
  "key_points": ["point1", "point2"],
  "entities": ["important names, companies, tools"]
}}

Return ONLY valid JSON with no extra text.

Content:
{content}
"""

    if mode == "translate":
        return f"""
{base_instruction}

Translate this content into clear {language} and preserve the original meaning.
If text is already in {language}, improve readability while preserving meaning.
Return only the translated text.

{content}
"""

    if mode == "quiz":
        return f"""
{base_instruction}

Create a {detail_line} quiz with EXACTLY {quiz_count} questions and answers from this content.
STRICT OUTPUT TEMPLATE:
Quiz:
Q1: ...
A1: ...
Q2: ...
A2: ...

{content}
"""

    if mode == "action_items":
        return f"""
{base_instruction}

Extract actionable next steps from this content.
Return as a numbered list.

{content}
"""

    if mode == "fact_check":
        task_text = task.strip() or "List verifiable claims and what evidence would validate each claim."
        return f"""
{base_instruction}

Fact-check this content for the following objective:
{task_text}

Create a {detail_line} fact-check report with EXACTLY {fact_claim_count} claims.
STRICT OUTPUT TEMPLATE:
Fact Check:
Claim 1: ...
Status 1: Supported | Contradicted | Unclear
Confidence 1: High | Medium | Low
Evidence 1: ...

{content}
"""

    raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")


def _get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _enforce_api_key(request: Request) -> None:
    expected_key = os.getenv("WEBLENS_API_KEY", "").strip()
    if not expected_key:
        return

    received_key = request.headers.get("x-api-key", "").strip()
    if received_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _enforce_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    with _rate_limit_lock:
        hits = _rate_limit_store[client_ip]
        while hits and now - hits[0] > RATE_LIMIT_WINDOW_SEC:
            hits.popleft()

        if len(hits) >= RATE_LIMIT_PER_WINDOW:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        hits.append(now)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    try:
        response = await call_next(request)
    except Exception:
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Unhandled internal error",
                "request_id": request_id,
            },
        )

    response.headers["X-Request-ID"] = request_id
    return response


@app.post("/analyze", response_model=PageResponse)
async def analyze_page(data: PageRequest, request: Request):
    _enforce_api_key(request)
    _enforce_rate_limit(request)

    request_id = _get_request_id(request)

    if not data.content.strip():
        raise HTTPException(status_code=400, detail="Page content is empty")

    mode = _normalize_mode(data.mode)
    if mode not in SUPPORTED_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {data.mode}")

    trimmed_content = data.content[:MAX_CONTENT_CHARS]
    detail = _normalize_detail(data.detail)
    language = _normalize_language(data.language)

    key = _cache_key(
        mode=mode,
        task=f"{data.task}|lang={language}|detail={detail}",
        content=trimmed_content,
    )
    cached = _cache_get(key)
    if cached is not None:
        return PageResponse(result=cached, request_id=request_id)

    prompt = build_prompt(
        mode=mode,
        task=data.task,
        content=trimmed_content,
        language=language,
        detail=detail,
    )

    try:
        try:
            client = get_client()
        except Exception as exc:
            fallback = _local_mode_fallback(
                mode,
                data.task,
                trimmed_content,
                reason=_friendly_model_reason(exc),
                language=language,
                detail=detail,
            )
            _cache_put(key, fallback)
            return PageResponse(result=fallback, request_id=request_id)

        response_text = _generate_with_timeout(client=client, model=_active_model_name(), contents=prompt)

        if not response_text:
            raise HTTPException(status_code=502, detail="Empty response from model")

        if mode == "extract":
            try:
                parsed = json.loads(_extract_json_text(response_text))
                result = json.dumps(parsed, indent=2)
                _cache_put(key, result)
                return PageResponse(result=result, request_id=request_id)
            except json.JSONDecodeError:
                raise HTTPException(status_code=502, detail="Model did not return valid JSON")

        formatted = _format_mode_output(
            mode=mode,
            raw=response_text,
            source_content=trimmed_content,
            task=data.task,
            language=language,
            detail=detail,
        )
        _cache_put(key, formatted)
        return PageResponse(result=formatted, request_id=request_id)

    except HTTPException:
        if mode in SUPPORTED_MODES:
            fallback = _local_mode_fallback(
                mode,
                data.task,
                trimmed_content,
                language=language,
                detail=detail,
            )
            _cache_put(key, fallback)
            return PageResponse(result=fallback, request_id=request_id)
        raise
    except Exception as exc:
        fallback = _local_mode_fallback(
            mode,
            data.task,
            trimmed_content,
            reason=_friendly_model_reason(exc),
            language=language,
            detail=detail,
        )
        _cache_put(key, fallback)
        return PageResponse(result=fallback, request_id=request_id)


@app.post("/analyze-visual", response_model=VisualResponse)
async def analyze_visual(data: VisualRequest, request: Request):
    _enforce_api_key(request)
    _enforce_rate_limit(request)

    request_id = _get_request_id(request)
    target_path = Path(data.input_path).expanduser()
    try:
        from detect import run_detection  # Local import to avoid hard dependency during text-only use.
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Visual detector is unavailable: {exc}")

    result = run_detection(
        input_path=target_path,
        model_name=data.model,
        conf=data.conf,
        frame_step=data.frame_step,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)

    return VisualResponse(result=result, request_id=request_id)


@app.get("/")
async def health(request: Request):
    return {
        "status": "WebLens backend running",
        "request_id": _get_request_id(request),
        "provider": _get_env_provider(),
        "model": _active_model_name(),
    }


@app.get("/debug-config")
async def debug_config(request: Request):
    _reload_env()
    gemini_key = _sanitize_key(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    openai_key = _sanitize_key(os.getenv("OPENAI_API_KEY"))
    provider = _get_env_provider()

    return {
        "request_id": _get_request_id(request),
        "provider": provider,
        "model": _active_model_name(),
        "gemini_key_present": bool(gemini_key),
        "gemini_key_masked": _masked_key(gemini_key),
        "gemini_key_prefix_ok": gemini_key.startswith("AIza") if gemini_key else False,
        "openai_key_present": bool(openai_key),
        "openai_key_masked": _masked_key(openai_key),
    }


@app.get("/models")
async def list_models(request: Request):
    _enforce_api_key(request)
    _enforce_rate_limit(request)

    try:
        client = get_client()
        models = client.models.list()
        return {
            "models": [m.name for m in models],
            "request_id": _get_request_id(request),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {exc}")
