"""Voice: OpenRouter STT/TTS clients + spoken-turn scoring.

Hermetic — HTTP is faked with `respx`, so no audio ever leaves the machine and no
API key is needed.
"""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from app.ai import audio as audio_mod
from app.core.config import settings
from app.core.errors import UpstreamError, ValidationError
from app.services import pronunciation as pron

STT_URL = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/audio/transcriptions"
TTS_URL = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/audio/speech"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch):
    # The clients refuse to run without a key; a dummy is enough for faked HTTP.
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")


# ── Format detection ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename,content_type,expected",
    [
        ("turn.wav", None, "wav"),
        ("turn.mp3", None, "mp3"),
        (None, "audio/webm;codecs=opus", "webm"),   # what MediaRecorder sends
        (None, "audio/x-wav", "wav"),
        (None, None, "webm"),                       # sensible browser default
        ("weird.xyz", "audio/flac", "flac"),
    ],
)
def test_audio_format_detection(filename, content_type, expected):
    assert audio_mod._normalise_format(filename, content_type) == expected


# ── STT ───────────────────────────────────────────────────────────────────────


@respx.mock
async def test_transcribe_returns_text_and_sends_base64():
    route = respx.post(STT_URL).mock(
        return_value=httpx.Response(
            200, json={"text": "Ich möchte einen Kaffee bitte.", "duration": 3.2}
        )
    )
    result = await audio_mod.transcribe(
        b"RIFFfake", filename="t.wav", language="de", model="openai/whisper-large-v3-turbo"
    )

    assert result.text == "Ich möchte einen Kaffee bitte."
    assert result.duration_s == 3.2

    sent = route.calls[0].request
    body = sent.read().decode()
    assert '"language":"de"' in body.replace(" ", "")
    # Audio must be base64 in input_audio, per the documented JSON shape.
    assert base64.b64encode(b"RIFFfake").decode() in body


async def test_transcribe_rejects_empty_audio():
    with pytest.raises(ValidationError):
        await audio_mod.transcribe(b"")


async def test_transcribe_rejects_oversized_audio():
    too_big = b"\x00" * (settings.max_audio_bytes + 1)
    with pytest.raises(ValidationError, match="too large"):
        await audio_mod.transcribe(too_big, filename="t.wav")


@respx.mock
async def test_transcribe_silence_is_an_error_not_an_empty_answer():
    respx.post(STT_URL).mock(return_value=httpx.Response(200, json={"text": "   "}))
    with pytest.raises(UpstreamError, match="silent"):
        await audio_mod.transcribe(
            b"x", filename="t.wav", model="openai/whisper-large-v3-turbo"
        )


@respx.mock
async def test_transcribe_maps_provider_5xx_to_a_friendly_message():
    respx.post(STT_URL).mock(return_value=httpx.Response(503, text="upstream boom"))
    with pytest.raises(UpstreamError) as exc:
        await audio_mod.transcribe(
            b"x", filename="t.wav", model="openai/whisper-large-v3-turbo"
        )
    # The learner should never see a raw provider body.
    assert "boom" not in str(exc.value)


# ── TTS ───────────────────────────────────────────────────────────────────────


@respx.mock
async def test_synthesize_returns_bytes_and_a_data_uri():
    respx.post(TTS_URL).mock(
        return_value=httpx.Response(
            200, content=b"ID3fakemp3", headers={"content-type": "audio/mpeg"}
        )
    )
    speech = await audio_mod.synthesize("Guten Tag!", voice="alloy")

    assert speech.audio == b"ID3fakemp3"
    assert speech.media_type == "audio/mpeg"
    assert speech.as_data_uri().startswith("data:audio/mpeg;base64,")


async def test_synthesize_rejects_empty_text():
    with pytest.raises(ValidationError):
        await audio_mod.synthesize("   ")


@respx.mock
async def test_synthesize_truncates_a_runaway_reply():
    route = respx.post(TTS_URL).mock(return_value=httpx.Response(200, content=b"x"))
    await audio_mod.synthesize("wort " * 2000)
    body = route.calls[0].request.read().decode()
    # Guard against generating a minutes-long clip from a runaway model reply.
    assert len(body) < 12_000


# ── Fluency scoring (mechanical, no model) ────────────────────────────────────


def test_fluency_rewards_a_pace_in_the_expected_band():
    # 30 words in 20s = 90 wpm, inside A2's 55-120 band.
    text = " ".join(["wort"] * 30)
    score, _ = pron.score_fluency(text, duration_s=20.0, cefr_level="A2")
    assert score == pytest.approx(1.0)


def test_fluency_penalises_a_very_slow_pace():
    text = " ".join(["wort"] * 5)
    score, notes = pron.score_fluency(text, duration_s=60.0, cefr_level="B1")
    assert score < 0.5
    assert any("slow" in n for n in notes)


def test_a1_slow_speech_is_not_punished_like_b2():
    text = " ".join(["wort"] * 15)  # 45 wpm over 20s
    a1, _ = pron.score_fluency(text, 20.0, "A1")
    c1, _ = pron.score_fluency(text, 20.0, "C1")
    # The same pace should score better for a beginner than for an advanced learner.
    assert a1 > c1


def test_repeated_fillers_reduce_fluency():
    clean = " ".join(["wort"] * 20)
    filled = " ".join(["also", "ähm"] * 10)
    s_clean, _ = pron.score_fluency(clean, 15.0, "A2")
    s_filled, _ = pron.score_fluency(filled, 15.0, "A2")
    assert s_filled < s_clean


def test_a_single_also_is_not_treated_as_hesitation():
    # "also" is a real German word; only repetition signals hesitation.
    once = "Also ich möchte einen Kaffee trinken bitte schön danke"
    score, _ = pron.score_fluency(once, 8.0, "A2")
    assert score > 0.8


def test_empty_transcript_scores_zero():
    score, notes = pron.score_fluency("", 5.0, "A2")
    assert score == 0.0 and notes


def test_missing_duration_still_produces_a_score():
    """The browser doesn't always report clip length; don't guess a speed."""
    score, _ = pron.score_fluency("ich möchte einen Kaffee", None, "A2")
    assert 0.0 < score <= 1.0


# ── Pronunciation proxy ───────────────────────────────────────────────────────


def test_clean_german_scores_well():
    score, _ = pron.score_pronunciation_proxy("Ich möchte einen Kaffee bitte")
    assert score > 0.85


def test_fragmentary_transcript_scores_lower_and_advises():
    score, notes = pron.score_pronunciation_proxy("ge ka st mö ei ka")
    assert score < 0.75
    assert notes


def test_pronunciation_is_always_flagged_approximate():
    """We don't run a phoneme aligner, so the API must not present this as a grade."""
    scores = pron.combine(pronunciation=0.9, grammar=0.8, fluency=0.7, notes=[])
    assert scores.pronunciation_is_approximate is True
    assert scores.as_dict()["pronunciation_is_approximate"] is True


def test_overall_weights_grammar_most():
    strong_grammar = pron.combine(pronunciation=0.2, grammar=1.0, fluency=0.2, notes=[])
    strong_pron = pron.combine(pronunciation=1.0, grammar=0.2, fluency=0.2, notes=[])
    assert strong_grammar.overall > strong_pron.overall


def test_scores_stay_in_range():
    for p, g, f in [(0, 0, 0), (1, 1, 1), (0.5, 0.9, 0.3)]:
        s = pron.combine(pronunciation=p, grammar=g, fluency=f, notes=[])
        assert 0.0 <= s.overall <= 1.0


# ── STT via multimodal chat (the default path) ────────────────────────────────

CHAT_URL = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"


@respx.mock
async def test_default_model_transcribes_through_chat_completions():
    """The dedicated /audio/* endpoints are guardrail-blocked on many accounts, so
    the default STT model is a multimodal chat model and must use /chat/completions."""
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "google/gemini-2.5-flash",
                "choices": [{"message": {"content": "Guten Tag, ich möchte einen Kaffee."}}],
            },
        )
    )
    result = await audio_mod.transcribe(b"RIFFfake", filename="t.wav")

    assert result.text == "Guten Tag, ich möchte einen Kaffee."
    body = route.calls[0].request.read().decode()
    assert "input_audio" in body
    assert base64.b64encode(b"RIFFfake").decode() in body


@respx.mock
async def test_chat_transcription_strips_a_wrapping_quote():
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": '"Guten Tag."'}}]}
        )
    )
    result = await audio_mod.transcribe(b"x", filename="t.wav")
    assert result.text == "Guten Tag."


@respx.mock
async def test_chat_transcription_treats_no_speech_marker_as_silence():
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "[no speech]"}}]}
        )
    )
    with pytest.raises(UpstreamError, match="silent"):
        await audio_mod.transcribe(b"x", filename="t.wav")


@respx.mock
async def test_tts_404_raises_SpeechUnavailable_for_browser_fallback():
    """A blocked account is permanent, not transient — the caller must be able to
    tell the difference so it can delegate to browser SpeechSynthesis."""
    respx.post(TTS_URL).mock(
        return_value=httpx.Response(404, json={"error": {"message": "No endpoints available"}})
    )
    with pytest.raises(audio_mod.SpeechUnavailable):
        await audio_mod.synthesize("Guten Tag.")


@respx.mock
async def test_tts_500_is_a_plain_upstream_error():
    respx.post(TTS_URL).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(UpstreamError) as exc:
        await audio_mod.synthesize("Guten Tag.")
    assert not isinstance(exc.value, audio_mod.SpeechUnavailable)


# ── Silent-turn recovery ──────────────────────────────────────────────────────


def test_unintelligible_turn_is_a_retry_not_a_dead_session() -> None:
    """Regression: a silent recording at question 10/10 surfaced
    "Nothing was transcribed — the recording may be silent." as an SSE `error`
    and the session ended with no wrap-up and no feedback.

    A hands-free conversation WILL produce silent turns — a cough, a false VAD
    trigger, someone thinking out loud. The handler must ask the learner to
    repeat, keep the session alive, and NOT consume one of the ten questions.
    The counter is derived from persisted assistant messages, so "don't consume
    a question" means: return before anything is written.
    """
    import inspect

    from app.api.v1 import speaking

    src = inspect.getsource(speaking.speaking_turn)
    # Just the handler body: from the except clause to the `return` that ends it.
    after_except = src.split("except UpstreamError")[1]
    retry_block = after_except.split("return", 1)[0]

    # Asks them to repeat, in character and in German…
    assert "wiederholen" in retry_block
    # …tells the client this was a retry, not a completed exchange…
    assert '"retry": True' in retry_block
    assert '"session_complete": False' in retry_block
    # …and returns BEFORE persisting, so the question counter holds.
    assert "return" in after_except
    assert "db.add(" not in retry_block


def test_session_feedback_is_spoken_in_the_learners_language() -> None:
    """The wrap-up coaches; it is not part of the German role-play.

    A learner who cannot yet read a German critique cannot act on it, so the
    feedback is generated in their native language AND the audio frame carries
    that language — otherwise the browser reads English coaching with a German
    voice, which is barely intelligible.
    """
    from app.api.v1.speaking import _FEEDBACK_INSTRUCTION, _SPEECH_LANG

    assert "{native_language}" in _FEEDBACK_INSTRUCTION
    # Read aloud → no markdown artefacts.
    assert "READ ALOUD" in _FEEDBACK_INSTRUCTION
    assert "no markdown" in _FEEDBACK_INSTRUCTION
    # A few languages the app supports must map to a real BCP-47 tag.
    for code, tag in (("tr", "tr-TR"), ("de", "de-DE"), ("ar", "ar-SA")):
        assert _SPEECH_LANG[code] == tag
