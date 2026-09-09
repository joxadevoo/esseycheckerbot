import re
from typing import Tuple, Optional

# Regex matches #essey, #essay, #insho, #task2 (case-insensitive)
HASHTAG_PATTERN = re.compile(r"#(essey|essay|insho|task2)\b", re.IGNORECASE)
MIN_WORD_COUNT = 40


def count_words(text: str) -> int:
    """Counts actual words in the text using IELTS whitespace standards (hyphenated words and contractions count as 1)."""
    if not text:
        return 0
    return len(text.strip().split())


def parse_task_components(clean_text: str, default_task_type: str = "Task 2") -> Tuple[str, Optional[str], str]:
    """
    Parses optional task_prompt and essay_text from clean text for Task 2.
    Handles formats like:
      - Topic: ... \n Essay: ...
      - Question: ... \n ...
      - task_prompt: ... \n essay_text: ...
    """
    task_type = "Task 2"

    prompt_patterns = [
        r"(?:task_prompt|topic|question|savol)\s*:\s*(.+?)(?:\n\s*(?:essay_text|essay|insho|javob)\s*:\s*|\n\n|\n)(.+)",
    ]

    for pat in prompt_patterns:
        m = re.search(pat, clean_text, re.IGNORECASE | re.DOTALL)
        if m:
            task_prompt = m.group(1).strip()
            essay_body = m.group(2).strip()
            if count_words(essay_body) >= 15:
                return task_type, task_prompt, essay_body

    return task_type, None, clean_text


def filter_essay_text(text: Optional[str]) -> Tuple[bool, Optional[str], Optional[str], int, str, Optional[str]]:
    """
    Applies the 3-tier filter to incoming text:
    1. Filter: Not a bot command (/start, /help, etc.)
    2. Filter: Contains valid essay hashtag (#essey, #essay, #insho, #task2)
    3. Filter: Minimum word length (>= 40 words)

    Returns:
        (is_valid, reject_reason, clean_text, word_count, task_type, task_prompt)
    """
    if not text or not text.strip():
        return False, "Matn bo'sh", None, 0, "Task 2", None

    stripped = text.strip()

    # Filter 1: Ignore commands
    if stripped.startswith("/"):
        return False, "Bot komandasi", None, 0, "Task 2", None

    # Filter 2: Must have hashtag
    match = HASHTAG_PATTERN.search(stripped)
    if not match:
        return False, "Hashtag topilmadi (masalan: #essay yoki #essey)", None, 0, "Task 2", None

    # Remove the hashtag from the text for evaluation
    raw_clean = HASHTAG_PATTERN.sub("", stripped).strip()
    task_type, task_prompt, clean_essay = parse_task_components(raw_clean, "Task 2")

    # Filter 3: Minimum word count
    words_count = count_words(clean_essay)
    if words_count < MIN_WORD_COUNT:
        return (
            False,
            f"Insho hajmi juda qisqa ({words_count} ta so'z). Kamida {MIN_WORD_COUNT} ta so'z bo'lishi kerak.",
            None,
            words_count,
            task_type,
            task_prompt,
        )

    return True, None, clean_essay, words_count, task_type, task_prompt
