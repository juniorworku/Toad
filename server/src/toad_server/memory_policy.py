"""Port of the server's explicit-save policy, rebranded for Toad."""

import re

QUESTIONS = re.compile(
    r"\b(do|did|can|could) you (still )?remember (what|when|where|who|how|if|whether|anything)\b"
    r"|\bdo you remember\b|\bdid you remember\b|\bwhat do you remember\b"
    r"|\bremember when\b|\b(i|you) (don'?t|do not|can'?t|cannot) remember\b"
    r"|\bwhat did i (ask|tell) you to remember\b"
)
REQUESTS = [
    re.compile(p)
    for p in [
        r"^((hey )?(buddy|toad)[,.!]?\s*)?((please|ok|okay|and|also|oh|so|alright|right)[,]?\s+)*"
        r"(remember|note|save|don'?t forget|do not forget|keep in mind|make a note|write (this|that|it) down|jot (this|that|it) down)\b",
        r"\b(can|could|would|will) you (please )?(remember|note|save|keep in mind|make a note|write (this|that|it) down)\b",
        r"\b(i want|i'd like|i would like|i need) you to (remember|note|save|keep in mind)\b",
        r"\b(please )?remember (that|this|to|my|i|i'm|me|it)\b",
        r"\b(save|store) (this|that|it)( for me| to (your )?memory)?\b",
        r"\badd (this|that|it) to (your )?(memory|memories|notes)\b",
        r"\bdon'?t let me forget\b|\bmake a note\b|\bnote (that|this|down)\b",
    ]
]
AFFIRMATIONS = re.compile(
    r"^(yes|yeah|yep|yup|sure|please|ok|okay|do it|go ahead|sounds good|please do|absolutely|definitely)\b"
)
OFFER = re.compile(r"\b(remember|save|note|keep)\b[^?]*\?")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


def allows_save(latest_user_words: str, previous_assistant_words: str | None) -> bool:
    said = normalize(latest_user_words)
    if not said:
        return False
    for sentence in re.split(r"(?<=[.!?])\s+", said):
        if any(pattern.search(sentence) for pattern in REQUESTS) and not QUESTIONS.search(sentence):
            return True
    return bool(
        previous_assistant_words
        and OFFER.search(normalize(previous_assistant_words))
        and AFFIRMATIONS.search(said)
    )
