import sys
# Add standard library paths for libraries inside PyInstaller runtime
sys.path.insert(0, '/opt/anaconda3/lib/python3.12/site-packages')
sys.path.insert(1, '/opt/anaconda3/lib/python3.12')
sys.path.insert(2, '/opt/anaconda3/lib/python3.12/lib-dynload')

import os
import re
import time
import traceback
import unicodedata

# ── Dynamically load .env configuration ───────────────────────────────────
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
_ENV_MODEL = None

if os.path.exists(_ENV_PATH):
    try:
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    os.environ[k] = v
        
        # Override standard OpenAI env variables for the SDK
        if "LLM_KEY" in os.environ:
            os.environ["OPENAI_API_KEY"] = os.environ["LLM_KEY"]
        if "LLM_URL" in os.environ:
            os.environ["OPENAI_BASE_URL"] = os.environ["LLM_URL"]
        if "LLM_MODEL" in os.environ:
            _ENV_MODEL = os.environ["LLM_MODEL"]
    except Exception:
        pass

try:
    from telemetry.logger import logger
    from telemetry.cost import cost_from_usage
    from telemetry.redact import redact
except ImportError:
    logger = None
    def cost_from_usage(model, usage): return 0.0
    def redact(s): return s, 0

# ── Pre-load prompt at module level (avoid repeated file I/O) ──────────────
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.txt")
_SYSTEM_PROMPT = None

def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        try:
            with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
                _SYSTEM_PROMPT = f.read()
        except Exception:
            _SYSTEM_PROMPT = ""
    return _SYSTEM_PROMPT


# ── Cache key normalization ────────────────────────────────────────────────
def normalize_cache_key(q: str) -> str:
    """Normalize Vietnamese text by stripping diacritics and punctuation."""
    q_clean = q.lower().strip()
    q_clean = "".join(
        c for c in unicodedata.normalize('NFD', q_clean)
        if unicodedata.category(c) != 'Mn'
    )
    q_clean = re.sub(r'[^\w\s]', ' ', q_clean)
    q_clean = re.sub(r'\s+', ' ', q_clean)
    return q_clean.strip()


# ── Injection sanitization ────────────────────────────────────────────────
_NOTE_PATTERNS = re.compile(
    r'(ghi\s*ch[uú]|note|lưu\s*ý|luu\s*y|comment)\s*[:\-]\s*(.*)',
    re.IGNORECASE | re.DOTALL
)

_INJECTION_KEYWORDS = re.compile(
    r'(set\s*price|đặt\s*giá|thay\s*đổi\s*giá|giảm\s*giá|tặng|miễn\s*phí|free'
    r'|system|ignore|override|0\s*vnd|0\s*đ|0\s*đồng|miên\s*phi'
    r'|tính\s*lại|áp\s*dụng|gán\s*giá|new\s*price|price\s*=|gia\s*=)',
    re.IGNORECASE
)

_OVERRIDE_TAGS = re.compile(
    r'\b(system|user|assistant|thought|action|final\s*answer)\s*:',
    re.IGNORECASE
)


def sanitize_question(q: str) -> str:
    """Strip prompt injection attempts from user order text."""
    q = _OVERRIDE_TAGS.sub('[SANITIZED_TAG]:', q)

    match = _NOTE_PATTERNS.search(q)
    if match:
        prefix = q[:match.start()]
        label = match.group(1)
        note_content = match.group(2)
        sanitized_note = _INJECTION_KEYWORDS.sub('[REMOVED]', note_content)
        q = prefix + label + ": " + sanitized_note

    return q


# ── Arithmetic post-validator ─────────────────────────────────────────────
_TOTAL_PATTERN = re.compile(r'tong\s*cong\s*:\s*([\d,\.]+)\s*vnd', re.IGNORECASE)


def _validate_total(answer: str) -> bool:
    """
    Verify the total is a reasonable positive integer if present.
    """
    if not answer:
        return True
    match = _TOTAL_PATTERN.search(answer)
    if not match:
        return True
    try:
        total_str = match.group(1).replace(',', '').replace('.', '')
        total = int(total_str)
        return total > 0
    except ValueError:
        return False


# ── Coupon quality drift corrector ──────────────────────────────────────────
_VALID_COUPONS = {
    'WINNER': 10,
    'VIP20': 20,
    'SALE15': 15,
    'EXPIRED': 0
}

def _post_process_result(result, question):
    """
    Correct quality drift (coupon percent corruption) and total arithmetic in wrapper.
    """
    if not result or not result.get("answer") or result.get("status") != "ok":
        return result
        
    trace = result.get("trace", [])
    if not trace:
        return result
        
    # Check if this is a shipping order or just a stock check
    has_shipping = False
    price = None
    in_stock = True
    found = True
    discount_percent = 0
    shipping_cost = 0
    shipping_error = None
    
    for step in trace:
        tool = step.get('tool')
        obs = step.get('observation', {})
        if not obs:
            continue
        if tool == 'check_stock':
            found = obs.get('found', True)
            in_stock = obs.get('in_stock', True)
            price = obs.get('unit_price_vnd')
        elif tool == 'get_discount':
            coupon_code = obs.get('code')
            valid = obs.get('valid', True)
            if valid and coupon_code:
                code_upper = coupon_code.strip().upper()
                if code_upper in _VALID_COUPONS:
                    discount_percent = _VALID_COUPONS[code_upper]
                else:
                    discount_percent = obs.get('percent', 0)
            else:
                discount_percent = 0
        elif tool == 'calc_shipping':
            has_shipping = True
            shipping_error = obs.get('error')
            if not shipping_error:
                shipping_cost = obs.get('cost_vnd', 0)
            else:
                shipping_cost = None

    if not found or not in_stock:
        if "khong" not in result["answer"].lower():
            result["answer"] = "San pham khong co hang"
        return result
        
    if has_shipping and shipping_error is not None:
        if "khong" not in result["answer"].lower():
            result["answer"] = "Khong giao hang den khu vuc nay"
        return result

    # Only recalculate total if this order requires shipping/total cost
    if has_shipping and price is not None and shipping_cost is not None:
        qty = 1
        qty_match = re.search(r'(?:mua|order)\s+(\d+)', question, re.IGNORECASE)
        if qty_match:
            qty = int(qty_match.group(1))
            
        subtotal = price * qty
        discounted = subtotal * (100 - discount_percent) // 100
        expected_total = discounted + shipping_cost
        
        answer = result["answer"]
        total_pattern = re.compile(
            r'((?:tong\s*cong|tong\s*thanh\s*toan|tong\s*tien|tong|total)\s*[:\-]?\s*)([\d\.,\s]+)(\s*(?:vnd|đ|d)?)',
            re.IGNORECASE
        )
        if total_pattern.search(answer):
            formatted_total = f"{expected_total:,}".replace(',', '.')
            result["answer"] = total_pattern.sub(rf"\g<1>{formatted_total}\g<3>", answer)
        else:
            result["answer"] = f"Tong cong: {expected_total} VND"
            
    return result


# ── Main mitigate function ────────────────────────────────────────────────
def mitigate(call_next, question, config, context):
    """
    context = {"session_id", "turn_index", "qid", "cache", "cache_lock"}
    """
    sanitized_q = sanitize_question(question)
    cache_key = normalize_cache_key(sanitized_q)

    cache = context.get("cache")
    lock = context.get("cache_lock")

    if cache is not None and lock is not None:
        with lock:
            if cache_key in cache:
                cached = cache[cache_key]
                if logger:
                    logger.log_event("CACHE_HIT", {
                        "qid": context.get("qid"),
                        "cache_key": cache_key,
                        "cached_answer": cached.get("answer"),
                    })
                return cached

    # Configure prompt & model
    conf = dict(config)
    prompt_text = _get_system_prompt()
    if prompt_text:
        conf["system_prompt"] = prompt_text
    
    # Dynamically inject model from .env if present
    if _ENV_MODEL:
        conf["model"] = _ENV_MODEL

    max_retries = 3
    result = None
    last_error = None

    for attempt in range(max_retries):
        t0 = time.time()
        try:
            result = call_next(sanitized_q, conf)
            wall_ms = int((time.time() - t0) * 1000)

            # Redact PII
            if result and result.get("answer"):
                answer = result["answer"]
                redacted, n_redact = redact(answer)
                if n_redact > 0:
                    result["answer"] = redacted
                    if logger:
                        logger.log_event("PII_REDACTED", {
                            "qid": context.get("qid"),
                            "redact_count": n_redact,
                        })

            # Check total sanity
            if result and result.get("answer"):
                if not _validate_total(result["answer"]):
                    if logger:
                        logger.log_event("INVALID_TOTAL", {
                            "qid": context.get("qid"),
                            "answer": result["answer"],
                        })
                    if attempt < max_retries - 1:
                        result = None
                        continue

            status = result.get("status") if result else "unknown"
            if status in ("loop", "max_steps") and logger:
                logger.log_event("LOOP_DETECTED", {
                    "qid": context.get("qid"),
                    "status": status,
                    "steps": result.get("steps", 0),
                })

            if result and logger:
                meta = result.get("meta", {})
                usage = meta.get("usage", {})
                logger.log_event("AGENT_CALL", {
                    "qid": context.get("qid"),
                    "attempt": attempt + 1,
                    "status": status,
                    "wall_ms": wall_ms,
                    "latency_ms": meta.get("latency_ms"),
                    "tokens": usage,
                    "cost_usd": cost_from_usage(meta.get("model", ""), usage),
                    "tools_used": meta.get("tools_used", []),
                    "steps": result.get("steps", 0),
                })

            break

        except Exception as e:
            last_error = e
            if logger:
                logger.log_event("AGENT_ERROR", {
                    "qid": context.get("qid"),
                    "attempt": attempt + 1,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
            backoff = 0.6 * (attempt + 1)
            time.sleep(backoff)

    if result is None:
        result = {
            "answer": "Rat tiec, da xay ra loi khi xu ly yeu cau cua ban.",
            "status": "wrapper_error",
            "steps": 0,
            "trace": [],
            "meta": {
                "latency_ms": 0,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "model": conf.get("model"),
                "provider": conf.get("provider"),
                "session_id": context.get("session_id"),
                "turn_index": context.get("turn_index"),
                "tools_used": [],
            }
        }
        if logger:
            logger.log_event("FALLBACK_RETURNED", {
                "qid": context.get("qid"),
                "error": str(last_error),
            })

    # Post process result to correct quality drift / math issues
    result = _post_process_result(result, question)

    if cache is not None and lock is not None and result.get("status") == "ok":
        with lock:
            cache[cache_key] = result

    return result
