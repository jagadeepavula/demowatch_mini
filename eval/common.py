"""Shared matching helper used by run_eval.py and verify_golden.py."""
import re


def has(text: str, fact) -> bool:
    """True if `fact` appears in `text` as a whole word/number (case-insensitive).
    `fact` is a string, or a list of strings meaning "any of these"."""
    alts = fact if isinstance(fact, list) else [fact]
    t = text.lower()
    for a in alts:
        pat = r"(?<![\w.:-])" + re.escape(a.lower()) + r"(?![\w])(?!:\d)"
        if re.search(pat, t):
            return True
    return False
