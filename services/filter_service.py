import re
from typing import Tuple, Optional

# Regex for student essays: #essay, #essey, #insho (case-insensitive)
HASHTAG_PATTERN = re.compile(r"#(essey|essay|insho)\b", re.IGNORECASE)

# Regex for teacher topics/prompts: #task2, #topic, #savol (case-insensitive)
TOPIC_HASHTAG_PATTERN = re.compile(r"#(task2|topic|savol)\b", re.IGNORECASE)

MIN_WORD_COUNT = 40
MAX_WORD_COUNT = 500


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


IELTS_TOPIC_KEYWORDS = [
    r"\bagree\s+or\s+disagree\b",
    r"\bdiscuss\s+both\s+(?:views|sides)\b",
    r"\bpositive\s+or\s+negative\s+(?:development|trend|impact)?\b",
    r"\badvantages\s+(?:and\s+disadvantages|outweigh)\b",
    r"\bcauses\s+and\s+solutions\b",
    r"\bproblems?\s+and\s+solutions?\b",
    r"\bto\s+what\s+extent\b",
    r"\bwhat\s+are\s+the\s+(?:reasons|causes|solutions|effects)\b",
    r"\bdo\s+you\s+(?:agree|think|believe)\b",
    r"\bgive\s+reasons\s+for\s+your\s+answer\b",
    r"\bwrite\s+about\s+the\s+following\s+topic\b",
    r"^(?:topic|savol|question|mavzu|prompt)\s*:",
]
IELTS_TOPIC_RE = re.compile("|".join(IELTS_TOPIC_KEYWORDS), re.IGNORECASE)


def is_probable_topic(text: str) -> bool:
    """
    Determines if the given text is an IELTS Task 2 topic/prompt rather than an essay.
    Criteria:
    - 5 <= word count < 120
    - Contains '?' OR IELTS prompt phrasing (agree/disagree, discuss both, etc.) OR explicit topic prefix
    """
    if not text:
        return False
    words = count_words(text)
    if words < 5 or words >= 120:
        return False

    # If the text explicitly has 'Topic: ... \n Essay: ...' with substantial essay body, it's not JUST a topic
    _, prompt, body = parse_task_components(text)
    if prompt and count_words(body) >= 30:
        return False

    # Check for question mark or typical IELTS prompt phrasing
    if "?" in text or IELTS_TOPIC_RE.search(text):
        return True

    # Check if text starts with explicit topic marker
    stripped = text.strip().lower()
    if stripped.startswith(("topic:", "savol:", "mavzu:", "question:", "prompt:")):
        return True

    return False


def filter_essay_text(text: Optional[str]) -> Tuple[bool, Optional[str], Optional[str], int, str, Optional[str]]:
    """
    Applies the 3-tier filter to incoming text:
    1. Filter: Not a bot command (/start, /help, etc.)
    2. Filter: Contains valid essay hashtag (#essey, #essay, #insho, #task2)
    3. Filter: Word count limits (MIN_WORD_COUNT <= words <= MAX_WORD_COUNT)

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

    # Filter 3: Word count limits
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

    if words_count > MAX_WORD_COUNT:
        return (
            False,
            f"Insho hajmi juda katta ({words_count} ta so'z). IELTS Task 2 inshosi {MAX_WORD_COUNT} ta so'zdan oshmasligi lozim.",
            None,
            words_count,
            task_type,
            task_prompt,
        )

    return True, None, clean_essay, words_count, task_type, task_prompt
