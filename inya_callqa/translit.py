"""Rough Indic-script to Latin transliteration plus a phonetic key for comparing
code-mixed ASR hypotheses.

Gnani's Stats API returns one hypothesis per configured language for every user
turn (e.g. ``{"en-IN": "how much is my due amount", "hi-IN": "हाउ मच इज़ माइ ड्यू अमाउंट"}``).
To ask "did both recognisers hear the same sounds?" we need both strings in one
alphabet. The Brahmic Unicode blocks share a layout (offset 0x15 is "ka" in
Devanagari, Bengali, Gurmukhi, Gujarati, Telugu, Kannada, Malayalam...), so one
offset table covers all of them. Accuracy is "good enough to compare sounds",
nothing more.
"""

from __future__ import annotations

import re
import unicodedata

# Block start -> script name. Each block is 0x80 wide.
BLOCKS = {
    0x0900: "devanagari",
    0x0980: "bengali",
    0x0A00: "gurmukhi",
    0x0A80: "gujarati",
    0x0B00: "oriya",
    0x0B80: "tamil",
    0x0C00: "telugu",
    0x0C80: "kannada",
    0x0D00: "malayalam",
}

INDEPENDENT_VOWELS = {
    0x05: "a", 0x06: "aa", 0x07: "i", 0x08: "ii", 0x09: "u", 0x0A: "uu",
    0x0B: "ri", 0x0D: "e", 0x0E: "e", 0x0F: "e", 0x10: "ai", 0x11: "o",
    0x12: "o", 0x13: "o", 0x14: "au",
}
CONSONANTS = {
    0x15: "k", 0x16: "kh", 0x17: "g", 0x18: "gh", 0x19: "ng", 0x1A: "ch",
    0x1B: "chh", 0x1C: "j", 0x1D: "jh", 0x1E: "ny", 0x1F: "t", 0x20: "th",
    0x21: "d", 0x22: "dh", 0x23: "n", 0x24: "t", 0x25: "th", 0x26: "d",
    0x27: "dh", 0x28: "n", 0x29: "n", 0x2A: "p", 0x2B: "ph", 0x2C: "b",
    0x2D: "bh", 0x2E: "m", 0x2F: "y", 0x30: "r", 0x31: "r", 0x32: "l",
    0x33: "l", 0x34: "zh", 0x35: "v", 0x36: "sh", 0x37: "sh", 0x38: "s",
    0x39: "h",
    # Devanagari precomposed nukta letters
    0x58: "q", 0x59: "kh", 0x5A: "g", 0x5B: "z", 0x5C: "r", 0x5D: "rh",
    0x5E: "f", 0x5F: "y",
}
VOWEL_SIGNS = {
    0x3E: "aa", 0x3F: "i", 0x40: "ii", 0x41: "u", 0x42: "uu", 0x43: "ri",
    0x44: "rii", 0x45: "e", 0x46: "e", 0x47: "e", 0x48: "ai", 0x49: "o",
    0x4A: "o", 0x4B: "o", 0x4C: "au", 0x57: "au",
}
NUKTA_MAP = {"j": "z", "ph": "f", "k": "q", "d": "r", "dh": "rh"}
NASALS = {0x01, 0x02, 0x70}  # candrabindu, anusvara, gurmukhi tippi
VISARGA = 0x03
NUKTA = 0x3C
VIRAMA = 0x4D
SCHWA_DELETING = {"devanagari", "gurmukhi", "gujarati", "bengali"}


def block_of(ch: str) -> tuple[int, str] | None:
    cp = ord(ch)
    base = cp & ~0x7F
    if base in BLOCKS:
        return cp - base, BLOCKS[base]
    return None


def has_indic(text: str) -> bool:
    return any(block_of(c) for c in text)


def scripts_in(text: str) -> set[str]:
    out = set()
    for c in text:
        b = block_of(c)
        if b:
            out.add(b[1])
        elif "a" <= c.lower() <= "z":
            out.add("latin")
    return out


def to_latin(text: str) -> str:
    """Transliterate any Brahmic-script runs in ``text`` to rough Latin."""
    text = unicodedata.normalize("NFC", text)
    out: list[str] = []
    pending_a = False  # a consonant was emitted and still carries its inherent "a"
    script = None

    def flush_schwa(word_end: bool) -> None:
        nonlocal pending_a
        if pending_a:
            if not (word_end and script in SCHWA_DELETING):
                out.append("a")
            pending_a = False

    for ch in text:
        b = block_of(ch)
        if b is None:
            flush_schwa(word_end=True)
            out.append(ch)
            continue
        off, script = b
        if off in CONSONANTS:
            flush_schwa(word_end=False)
            out.append(CONSONANTS[off])
            pending_a = True
        elif off == NUKTA:
            if out and out[-1] in NUKTA_MAP:
                out[-1] = NUKTA_MAP[out[-1]]
        elif off in VOWEL_SIGNS:
            pending_a = False
            out.append(VOWEL_SIGNS[off])
        elif off == VIRAMA:
            pending_a = False
        elif off in INDEPENDENT_VOWELS:
            flush_schwa(word_end=False)
            out.append(INDEPENDENT_VOWELS[off])
        elif off in NASALS:
            flush_schwa(word_end=False)
            out.append("n")
        elif off == VISARGA:
            flush_schwa(word_end=False)
            out.append("h")
        elif 0x66 <= off <= 0x6F:
            flush_schwa(word_end=True)
            out.append(str(off - 0x66))
        # anything else (avagraha, danda, addak) is dropped
    flush_schwa(word_end=True)
    return "".join(out)


_DIGRAPHS = [
    ("chh", "c"), ("ch", "c"), ("sh", "s"), ("ph", "f"), ("bh", "b"),
    ("kh", "k"), ("gh", "g"), ("jh", "j"), ("th", "t"), ("dh", "d"),
    ("zh", "l"), ("ck", "k"), ("q", "k"), ("x", "ks"), ("w", "v"), ("z", "s"),
]


def phonetic_key(text: str) -> str:
    """Collapse spelling differences between an English-spelled and a
    transliterated hypothesis: drop h/y, merge aspirates, fold every vowel run
    to "a", strip English silent final "e", squeeze doubled letters."""
    words = re.findall(r"[a-z0-9]+", to_latin(text).lower())
    keys = []
    for w in words:
        if len(w) >= 3 and w.endswith("e") and w[-2] not in "aeiou":
            w = w[:-1]
        w = w.replace("igh", "i")  # "mighty", "high": silent gh
        w = re.sub(r"c(?=[eiy])", "s", w)  # soft c: "cancel", "city"
        w = re.sub(r"c(?!h)", "k", w)  # hard c: "call"
        w = re.sub(r"(?<=[aeiou])w", "", w)  # "how", "law": w is part of the vowel
        for a, b in _DIGRAPHS:
            w = w.replace(a, b)
        w = re.sub(r"[hy]", "", w)
        w = re.sub(r"[aeiou]+", "a", w)
        w = re.sub(r"(.)\1+", r"\1", w)
        if w:
            keys.append(w)
    return " ".join(keys)


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def sound_similarity(a: str, b: str) -> float:
    """1.0 = same sounds, 0.0 = nothing in common."""
    ka, kb = phonetic_key(a), phonetic_key(b)
    if not ka and not kb:
        return 1.0
    return 1.0 - levenshtein(ka, kb) / max(len(ka), len(kb))
