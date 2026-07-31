"""Scoring a spoken turn: pronunciation, grammar, fluency.

Pronunciation is the awkward one. We don't run a phoneme-level aligner, so an
honest score needs care:

* **Fluency** we can measure mechanically — words per minute against a
  CEFR-appropriate band, plus filler-word density. No model needed.
* **Grammar** is a judgement the LLM makes well, via the same structured path
  the writing evaluator uses.
* **Pronunciation** we can only *approximate* from the transcript: if the STT
  model produced clean, expected German words, the learner was intelligible; if
  it produced garble or dropped words, they probably weren't. That's a real
  signal but a coarse one, so the API labels it `approximate` and the UI is
  expected to present it as guidance rather than a grade.

Being explicit about that beats inventing a confident-looking number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Rough words-per-minute bands for comfortable speech by level. A1 speakers are
# expected to be slow; penalising them for that would be wrong.
_WPM_TARGET = {
    "A1": (40, 100),
    "A2": (55, 120),
    "B1": (70, 140),
    "B2": (85, 160),
    "C1": (100, 180),
}

# German hesitation markers. Some ("also", "ja") are legitimate words, so they
# only count when repeated — see _filler_ratio.
_FILLERS = ("äh", "ähm", "ehm", "hmm", "öh", "also", "ja", "halt", "irgendwie")

_WORD_RE = re.compile(r"[\wäöüÄÖÜß]+", re.UNICODE)


@dataclass(slots=True)
class SpeechScores:
    pronunciation: float
    grammar: float
    fluency: float
    overall: float
    pronunciation_is_approximate: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "pronunciation": round(self.pronunciation, 2),
            "grammar": round(self.grammar, 2),
            "fluency": round(self.fluency, 2),
            "overall": round(self.overall, 2),
            "pronunciation_is_approximate": self.pronunciation_is_approximate,
            "notes": self.notes,
        }


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _filler_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    low = [t.lower() for t in tokens]
    # Count a filler only from its second occurrence: one "also" is speech, five
    # is hesitation.
    hits = 0
    for f in _FILLERS:
        n = low.count(f)
        if n > 1:
            hits += n - 1
    return hits / len(low)


def score_fluency(
    transcript: str, duration_s: float | None, cefr_level: str
) -> tuple[float, list[str]]:
    """Mechanical fluency from speech rate + hesitation. No model involved."""
    tokens = words(transcript)
    notes: list[str] = []

    if not tokens:
        return 0.0, ["Nothing was said."]

    filler = _filler_ratio(tokens)
    filler_penalty = min(filler * 2.0, 0.35)
    if filler > 0.08:
        notes.append("Quite a few hesitation words — try pausing silently instead.")

    if not duration_s or duration_s <= 0:
        # Without a duration we can't compute a rate; score on hesitation alone
        # rather than guessing a speed.
        return max(0.0, 0.75 - filler_penalty), notes

    wpm = len(tokens) / (duration_s / 60.0)
    low, high = _WPM_TARGET.get(cefr_level.upper(), _WPM_TARGET["A2"])

    if wpm < low:
        rate = max(0.3, wpm / low)
        notes.append(f"Speaking pace was slow (~{wpm:.0f} words/min).")
    elif wpm > high:
        # Too fast is a mild issue, not a failure.
        rate = max(0.7, 1.0 - (wpm - high) / (high * 2))
        notes.append(f"Speaking pace was quick (~{wpm:.0f} words/min).")
    else:
        rate = 1.0

    return max(0.0, min(1.0, rate - filler_penalty)), notes


def score_pronunciation_proxy(
    transcript: str, stt_confident: bool = True
) -> tuple[float, list[str]]:
    """Transcript-derived proxy — deliberately coarse, and flagged as such.

    Signals we can actually read: did the recogniser produce plausible German
    words, and did it fall back to fragments? Very short tokens and non-German
    character runs suggest the recogniser struggled, which usually means the
    speaker was hard to understand.
    """
    tokens = words(transcript)
    notes: list[str] = []
    if not tokens:
        return 0.0, ["No speech detected."]

    # Fragmentary output ("ge", "ka", "st") is a recogniser-struggled signal.
    fragments = sum(1 for t in tokens if len(t) <= 2)
    frag_ratio = fragments / len(tokens)

    # Latin-script German should have very few tokens with no vowel at all.
    vowelless = sum(1 for t in tokens if not re.search(r"[aeiouäöüyAEIOUÄÖÜY]", t))
    vowelless_ratio = vowelless / len(tokens)

    score = 1.0 - min(frag_ratio * 1.2, 0.4) - min(vowelless_ratio * 1.5, 0.3)
    if not stt_confident:
        score -= 0.1
    if frag_ratio > 0.25:
        notes.append(
            "Some words came through unclearly — try slowing down and "
            "over-articulating word endings."
        )
    return max(0.0, min(1.0, score)), notes


def combine(
    *, pronunciation: float, grammar: float, fluency: float, notes: list[str]
) -> SpeechScores:
    """Weighted overall. Grammar carries most weight: it's what we measure best."""
    overall = grammar * 0.45 + fluency * 0.3 + pronunciation * 0.25
    return SpeechScores(
        pronunciation=pronunciation,
        grammar=grammar,
        fluency=fluency,
        overall=overall,
        pronunciation_is_approximate=True,
        notes=notes,
    )
