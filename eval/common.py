"""Shared matching helpers used by run_eval.py, rescore.py and verify_golden.py."""
import re

NEGATORS = ("not ", "n't ", "no ", "never ", "without ")


def _find(text: str, a: str):
    a = a.strip().lower()            # "no " and "0 " in the dataset mean the word, not the trailing space
    pat = r"(?<![\w.:-])" + re.escape(a) + r"(?![\w])(?!:\d)"
    return list(re.finditer(pat, text.lower()))


def has(text: str, fact) -> bool:
    """True if `fact` appears in `text` as a whole word/number (case-insensitive).
    `fact` is a string, or a list of strings meaning "any of these"."""
    alts = fact if isinstance(fact, list) else [fact]
    return any(_find(text, a) for a in alts)


def forbidden(text: str, fact) -> bool:
    """True if a forbidden phrase appears AND is not negated.
    "not every incident is resolved" must not trip the rule against "every incident is resolved"."""
    alts = fact if isinstance(fact, list) else [fact]
    t = text.lower()
    for a in alts:
        for m in _find(text, a):
            before = t[max(0, m.start() - 12):m.start()]
            if not any(before.endswith(n) for n in NEGATORS):
                return True
    return False