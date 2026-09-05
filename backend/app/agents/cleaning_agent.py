"""Data cleaning agent - deduplication, text normalization, language filtering."""

import time
import re

from langdetect import DetectorFactory, LangDetectException, detect

from app.agents.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)

# langdetect samples randomly; seeding makes the same text always classify
# the same way, so a workflow re-run produces the same corpus.
DetectorFactory.seed = 0

# Below this many characters there is not enough signal to classify, so we
# keep the text rather than throwing away short comments like "battery died".
MIN_CHARS_FOR_DETECTION = 25

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    # Remove special characters but keep basic punctuation
    text = re.sub(r'[^\w\s.,!?\'"-]', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def is_english(text: str) -> bool:
    """Detect English using langdetect (naive Bayes over character n-grams).

    Short strings are kept rather than discarded: below ~25 characters the
    detector is unreliable, and dropping them would silently throw away
    terse but useful feedback.
    """
    if not text or not text.strip():
        return False

    stripped = text.strip()
    if len(stripped) < MIN_CHARS_FOR_DETECTION:
        return True

    try:
        return detect(stripped) == "en"
    except LangDetectException:
        # No detectable features (emoji only, digits only, etc.) - keep it
        # and let downstream sentiment scoring decide it is neutral.
        return True


# Backwards-compatible alias for the previous heuristic name.
is_english_simple = is_english

async def cleaning_node(state: AgentState) -> AgentState:
    logger.info("Agent starting: Cleaning", workflow_id=state.get("workflow_id"))
    state["current_agent"] = "cleaning"
    start_time = time.time()
    
    raw_data = state.get("raw_data", [])
    cleaned_data = []
    seen_content = set()
    
    for item in raw_data:
        content = item.get("content", "")
        
        # 1. Clean text
        cleaned_content = clean_text(content)
        
        # 2. Filter short/empty
        if len(cleaned_content) < 10:
            continue
            
        # 3. Deduplicate
        content_hash = hash(cleaned_content.lower())
        if content_hash in seen_content:
            continue
        seen_content.add(content_hash)
        
        # 4. Filter non-English
        if not is_english_simple(cleaned_content):
            continue
            
        cleaned_item = item.copy()
        cleaned_item["content"] = cleaned_content
        cleaned_data.append(cleaned_item)
        
    state["cleaned_data"] = cleaned_data
    
    execution_time = int((time.time() - start_time) * 1000)
    
    if "agent_logs" not in state:
        state["agent_logs"] = []
        
    state["agent_logs"].append({
        "agent_name": "cleaning",
        "status": "completed",
        "input_data": {"raw_count": len(raw_data)},
        "output_data": {"cleaned_count": len(cleaned_data), "removed": len(raw_data) - len(cleaned_data)},
        "execution_time_ms": execution_time
    })
    
    return state
