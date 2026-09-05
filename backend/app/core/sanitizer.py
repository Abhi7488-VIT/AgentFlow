"""
AgentFlow AI — Query Sanitizer

Central input sanitization layer that sits between user input and LLM prompts.
Prevents prompt injection, enforces length limits, and strips dangerous patterns.
"""

import re
import json
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────
MAX_QUERY_LENGTH = 500          # Max characters for user query
MAX_QUERY_WORDS = 60            # Max word count
MIN_QUERY_LENGTH = 2            # Reject empty/tiny queries

# Patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"you\s+are\s+now\s+(?:a|an|the)\s+",
    r"forget\s+(everything|all|your)\s+(you|instructions|rules)",
    r"new\s+instructions?\s*:",
    r"system\s*prompt\s*:",
    r"act\s+as\s+(?:a|an)\s+",
    r"pretend\s+(you\s+are|to\s+be)",
    r"roleplay\s+as",
    r"override\s+(your|the|all)\s+(instructions|rules|prompt)",
    r"do\s+not\s+follow\s+(your|the|previous)\s+(instructions|rules)",
    r"\[system\]",
    r"\[inst\]",
    r"<\s*system\s*>",
    r"<\s*/?\s*prompt\s*>",
    r"```\s*(system|instruction|prompt)",
    r"ADMIN\s*MODE",
    r"jailbreak",
    r"DAN\s*mode",
]

# Characters/sequences to strip (could break JSON or prompt structure)
DANGEROUS_CHARS = [
    '"""',           # Triple quotes could break f-string prompts
    "'''",
    "${",             # Template injection
    "{{",             # Jinja/prompt template escape
    "}}",
    "\\n\\n\\n",      # Excessive newlines
]


def sanitize_query(raw_query: str) -> tuple[str, list[str]]:
    """
    Sanitize user query before it touches any LLM prompt.
    
    Returns:
        tuple: (sanitized_query, list_of_warnings)
        
    Raises:
        ValueError: If the query is clearly malicious or invalid.
    """
    warnings = []
    
    if not raw_query or not raw_query.strip():
        raise ValueError("Query cannot be empty.")
    
    query = raw_query.strip()
    
    # ── 1. Length enforcement ──────────────────────
    if len(query) > MAX_QUERY_LENGTH:
        query = query[:MAX_QUERY_LENGTH]
        warnings.append(f"Query truncated to {MAX_QUERY_LENGTH} characters.")
        logger.warning("Query truncated", original_length=len(raw_query))
    
    word_count = len(query.split())
    if word_count > MAX_QUERY_WORDS:
        query = " ".join(query.split()[:MAX_QUERY_WORDS])
        warnings.append(f"Query truncated to {MAX_QUERY_WORDS} words.")
    
    if len(query.strip()) < MIN_QUERY_LENGTH:
        raise ValueError("Query is too short. Please enter a valid product or topic.")
    
    # ── 2. Strip dangerous characters ─────────────
    for char in DANGEROUS_CHARS:
        if char in query:
            query = query.replace(char, " ")
            warnings.append("Special characters removed.")
    
    # ── 3. Prompt injection detection ─────────────
    query_lower = query.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query_lower):
            logger.warning(
                "Prompt injection attempt detected",
                pattern=pattern,
                query_preview=query[:80]
            )
            raise ValueError(
                "Your query contains instructions that look like a prompt manipulation attempt. "
                "Please enter a normal product name or topic."
            )
    
    # ── 4. Normalize whitespace ───────────────────
    query = re.sub(r'\s+', ' ', query).strip()
    
    # ── 5. Strip any remaining control characters ─
    query = ''.join(c for c in query if c.isprintable())
    
    return query, warnings


def safe_query_for_prompt(query: str) -> str:
    """
    Wraps a sanitized query for safe insertion into an f-string prompt.
    Escapes any remaining characters that could interfere with prompt structure.
    """
    # Replace quotes that could break JSON schema examples in the prompt
    safe = query.replace('"', "'").replace("\\", "")
    return safe


def _balanced_object(text: str) -> str | None:
    """Return the first brace-balanced object, ignoring braces inside strings."""
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return None


def _repair_json(text: str) -> str:
    """Fix the malformations LLMs actually produce.

    Seen in practice: trailing commas before a closing bracket, curly
    quotes copied from prose, and raw newlines inside string values -
    which JSON forbids but a model writing a multi-paragraph summary
    emits freely.
    """
    # Curly quotes used where JSON needs straight ones.
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")

    # Trailing commas: {"a": 1,} or [1, 2,]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Escape control characters appearing inside string literals.
    control_map = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    out: list[str] = []
    in_string = False
    escaped = False

    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            elif char in control_map:
                out.append(control_map[char])
                continue
        elif char == '"':
            in_string = True
        out.append(char)

    return "".join(out)


def extract_json(text: str) -> dict:
    """Extract a JSON object from an LLM response.

    Models return JSON wrapped in markdown fences, with prose either side
    of it, with trailing commas, or with raw newlines inside strings. Each
    strategy below handles one of those and they are tried cheapest first,
    so the caller only sees a failure if every one of them fails.
    """
    if not text:
        raise ValueError("Cannot extract JSON from empty text")

    candidates: list[str] = [text]

    # Content inside a ```json ... ``` fence.
    fence = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.append(fence.group(1).strip())

    # The first brace-balanced object, ignoring braces inside strings.
    balanced = _balanced_object(text)
    if balanced:
        candidates.append(balanced)

    # Greedy slice from the first { to the last }.
    start_idx, end_idx = text.find("{"), text.rfind("}")
    if start_idx != -1 and end_idx > start_idx:
        candidates.append(text[start_idx:end_idx + 1])

    # strict=False tolerates control characters inside strings.
    parsers = (
        lambda c: json.loads(c),
        lambda c: json.loads(c, strict=False),
        lambda c: json.loads(_repair_json(c), strict=False),
    )

    for candidate in candidates:
        if not candidate or not candidate.strip():
            continue
        for parser in parsers:
            try:
                parsed = parser(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

    raise ValueError(f"Could not extract JSON from text: {text[:100]}...")
