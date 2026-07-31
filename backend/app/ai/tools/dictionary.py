"""German word lookup — dictionary-first, LLM as a labelled fallback.

Why curated-first: a wrong noun gender presented as fact is the kind of error a
learner internalises and repeats for years. The curated table below is data we
are *certain* about; anything not in it goes to the LLM, but the response is
tagged ``source="llm"`` so the UI can visually distinguish "verified" from
"model guess" rather than presenting both with equal authority.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import router as ai_router
from app.ai.structured import parse_json_object
from app.ai.tasks import TaskType
from app.core.errors import UpstreamError

log = structlog.get_logger(__name__)


# ── Curated table ──────────────────────────────────────────────────────────────
#
# ~120 high-frequency A1–B1 words. Nouns are keyed by their capitalised German
# form (article carried separately); verbs/adjectives by their lowercase base
# form. Every entry here has been hand-checked for gender/plural correctness —
# when we weren't sure, the word was left out rather than guessed.


def _n(
    article: str,
    plural: str | None,
    en: str,
    de_ex: str,
    en_ex: str,
    level: str,
    ipa: str | None = None,
) -> dict[str, Any]:
    return {
        "pos": "noun",
        "article": article,
        "plural": plural,
        "ipa": ipa,
        "meanings": [{"lang": "en", "text": en}],
        "examples": [{"de": de_ex, "en": en_ex}],
        "cefr_level": level,
    }


def _v(en: str, de_ex: str, en_ex: str, level: str, ipa: str | None = None) -> dict[str, Any]:
    return {
        "pos": "verb",
        "article": None,
        "plural": None,
        "ipa": ipa,
        "meanings": [{"lang": "en", "text": en}],
        "examples": [{"de": de_ex, "en": en_ex}],
        "cefr_level": level,
    }


def _a(en: str, de_ex: str, en_ex: str, level: str, ipa: str | None = None) -> dict[str, Any]:
    return {
        "pos": "adjective",
        "article": None,
        "plural": None,
        "ipa": ipa,
        "meanings": [{"lang": "en", "text": en}],
        "examples": [{"de": de_ex, "en": en_ex}],
        "cefr_level": level,
    }


CURATED: dict[str, dict[str, Any]] = {
    # ── Nouns ────────────────────────────────────────────────────────────────
    "Tisch": _n(
        "der",
        "die Tische",
        "table",
        "Der Tisch steht in der Küche.",
        "The table is in the kitchen.",
        "A1",
        "tɪʃ",
    ),
    "Stuhl": _n(
        "der", "die Stühle", "chair", "Der Stuhl ist neu.", "The chair is new.", "A1", "ʃtuːl"
    ),
    "Mann": _n(
        "der",
        "die Männer",
        "man",
        "Der Mann trinkt Kaffee.",
        "The man is drinking coffee.",
        "A1",
        "man",
    ),
    "Hund": _n(
        "der",
        "die Hunde",
        "dog",
        "Der Hund schläft im Garten.",
        "The dog is sleeping in the garden.",
        "A1",
        "hʊnt",
    ),
    "Katze": _n(
        "die",
        "die Katzen",
        "cat",
        "Die Katze sitzt auf dem Sofa.",
        "The cat is sitting on the sofa.",
        "A1",
        "ˈkatsə",
    ),
    "Tag": _n(
        "der",
        "die Tage",
        "day",
        "Heute ist ein schöner Tag.",
        "Today is a beautiful day.",
        "A1",
        "taːk",
    ),
    "Abend": _n(
        "der",
        "die Abende",
        "evening",
        "Am Abend lese ich gern.",
        "In the evening I like to read.",
        "A1",
    ),
    "Morgen": _n("der", "die Morgen", "morning", "Guten Morgen!", "Good morning!", "A1"),
    "Freund": _n(
        "der", "die Freunde", "friend", "Er ist mein bester Freund.", "He is my best friend.", "A1"
    ),
    "Lehrer": _n(
        "der",
        "die Lehrer",
        "teacher",
        "Der Lehrer erklärt die Grammatik.",
        "The teacher explains the grammar.",
        "A1",
    ),
    "Vater": _n(
        "der",
        "die Väter",
        "father",
        "Mein Vater arbeitet in Berlin.",
        "My father works in Berlin.",
        "A1",
    ),
    "Mutter": _n(
        "die",
        "die Mütter",
        "mother",
        "Meine Mutter kocht sehr gut.",
        "My mother cooks very well.",
        "A1",
    ),
    "Bruder": _n(
        "der",
        "die Brüder",
        "brother",
        "Mein Bruder ist älter als ich.",
        "My brother is older than me.",
        "A1",
    ),
    "Schwester": _n(
        "die",
        "die Schwestern",
        "sister",
        "Meine Schwester wohnt in München.",
        "My sister lives in Munich.",
        "A1",
    ),
    "Sohn": _n(
        "der", "die Söhne", "son", "Ihr Sohn geht in die Schule.", "Her son goes to school.", "A1"
    ),
    "Tochter": _n(
        "die",
        "die Töchter",
        "daughter",
        "Seine Tochter lernt Deutsch.",
        "His daughter is learning German.",
        "A1",
    ),
    "Kind": _n(
        "das",
        "die Kinder",
        "child",
        "Das Kind spielt im Park.",
        "The child is playing in the park.",
        "A1",
    ),
    "Frau": _n(
        "die",
        "die Frauen",
        "woman",
        "Die Frau liest ein Buch.",
        "The woman is reading a book.",
        "A1",
    ),
    "Familie": _n(
        "die",
        "die Familien",
        "family",
        "Wir essen als Familie zusammen.",
        "We eat together as a family.",
        "A1",
    ),
    "Apfel": _n(
        "der",
        "die Äpfel",
        "apple",
        "Der Apfel ist rot und süß.",
        "The apple is red and sweet.",
        "A1",
        "ˈapfl̩",
    ),
    "Baum": _n(
        "der",
        "die Bäume",
        "tree",
        "Der Baum vor dem Haus ist sehr alt.",
        "The tree in front of the house is very old.",
        "A1",
    ),
    "Auto": _n(
        "das",
        "die Autos",
        "car",
        "Das Auto steht vor der Tür.",
        "The car is parked in front of the door.",
        "A1",
        "ˈaʊto",
    ),
    "Zug": _n(
        "der",
        "die Züge",
        "train",
        "Der Zug fährt um acht Uhr ab.",
        "The train departs at eight o'clock.",
        "A2",
    ),
    "Bahnhof": _n(
        "der",
        "die Bahnhöfe",
        "train station",
        "Der Bahnhof ist nicht weit von hier.",
        "The train station is not far from here.",
        "A2",
    ),
    "Supermarkt": _n(
        "der",
        "die Supermärkte",
        "supermarket",
        "Ich kaufe Brot im Supermarkt.",
        "I buy bread at the supermarket.",
        "A1",
    ),
    "Preis": _n(
        "der",
        "die Preise",
        "price",
        "Der Preis für das Buch ist zu hoch.",
        "The price for the book is too high.",
        "A2",
    ),
    "Kaffee": _n(
        "der",
        "die Kaffees",
        "coffee",
        "Ich trinke jeden Morgen einen Kaffee.",
        "I drink a coffee every morning.",
        "A1",
        "ˈkafeː",
    ),
    "Wein": _n(
        "der",
        "die Weine",
        "wine",
        "Der Wein aus Italien schmeckt gut.",
        "The wine from Italy tastes good.",
        "A2",
    ),
    "Brot": _n(
        "das",
        "die Brote",
        "bread",
        "Ich esse morgens frisches Brot.",
        "I eat fresh bread in the morning.",
        "A1",
        "broːt",
    ),
    "Wasser": _n(
        "das", None, "water", "Ich trinke viel Wasser.", "I drink a lot of water.", "A1", "ˈvasɐ"
    ),
    "Milch": _n(
        "die", None, "milk", "Die Milch ist im Kühlschrank.", "The milk is in the fridge.", "A1"
    ),
    "Haus": _n(
        "das",
        "die Häuser",
        "house",
        "Wir wohnen in einem kleinen Haus.",
        "We live in a small house.",
        "A1",
        "haʊs",
    ),
    "Wohnung": _n(
        "die",
        "die Wohnungen",
        "apartment",
        "Die Wohnung hat zwei Zimmer.",
        "The apartment has two rooms.",
        "A2",
    ),
    "Zimmer": _n(
        "das", "die Zimmer", "room", "Mein Zimmer ist sehr hell.", "My room is very bright.", "A1"
    ),
    "Fenster": _n(
        "das",
        "die Fenster",
        "window",
        "Bitte mach das Fenster zu.",
        "Please close the window.",
        "A1",
    ),
    "Tür": _n("die", "die Türen", "door", "Die Tür ist geöffnet.", "The door is open.", "A1"),
    "Bett": _n(
        "das", "die Betten", "bed", "Das Bett steht am Fenster.", "The bed is by the window.", "A1"
    ),
    "Buch": _n(
        "das",
        "die Bücher",
        "book",
        "Ich lese ein spannendes Buch.",
        "I'm reading an exciting book.",
        "A1",
        "buːx",
    ),
    "Zeitung": _n(
        "die",
        "die Zeitungen",
        "newspaper",
        "Er liest jeden Tag die Zeitung.",
        "He reads the newspaper every day.",
        "A2",
    ),
    "Stadt": _n(
        "die", "die Städte", "city", "Berlin ist eine große Stadt.", "Berlin is a big city.", "A1"
    ),
    "Straße": _n(
        "die",
        "die Straßen",
        "street",
        "Die Straße ist sehr laut.",
        "The street is very loud.",
        "A1",
    ),
    "Schule": _n(
        "die",
        "die Schulen",
        "school",
        "Die Kinder gehen zur Schule.",
        "The children go to school.",
        "A1",
    ),
    "Universität": _n(
        "die",
        "die Universitäten",
        "university",
        "Sie studiert an der Universität.",
        "She studies at the university.",
        "B1",
    ),
    "Arbeit": _n(
        "die", "die Arbeiten", "work", "Die Arbeit macht mir Spaß.", "I enjoy the work.", "A2"
    ),
    "Zeit": _n(
        "die", "die Zeiten", "time", "Ich habe heute keine Zeit.", "I don't have time today.", "A1"
    ),
    "Woche": _n(
        "die",
        "die Wochen",
        "week",
        "Nächste Woche fahre ich nach Wien.",
        "Next week I'm going to Vienna.",
        "A1",
    ),
    "Jahr": _n(
        "das",
        "die Jahre",
        "year",
        "Dieses Jahr lerne ich Deutsch.",
        "This year I'm learning German.",
        "A1",
    ),
    "Sprache": _n(
        "die",
        "die Sprachen",
        "language",
        "Deutsch ist eine schwere Sprache.",
        "German is a difficult language.",
        "A2",
    ),
    "Frage": _n(
        "die",
        "die Fragen",
        "question",
        "Ich habe eine Frage zur Grammatik.",
        "I have a question about grammar.",
        "A1",
    ),
    "Antwort": _n(
        "die",
        "die Antworten",
        "answer",
        "Die Antwort war richtig.",
        "The answer was correct.",
        "A1",
    ),
    # ── Verbs ────────────────────────────────────────────────────────────────
    "sein": _v("to be", "Ich bin müde.", "I am tired.", "A1", "zaɪn"),
    "haben": _v("to have", "Ich habe einen Hund.", "I have a dog.", "A1", "ˈhaːbən"),
    "gehen": _v("to go", "Ich gehe nach Hause.", "I go home.", "A1", "ˈɡeːən"),
    "kommen": _v("to come", "Sie kommt aus Spanien.", "She comes from Spain.", "A1", "ˈkɔmən"),
    "machen": _v(
        "to do / make", "Was machst du gerade?", "What are you doing right now?", "A1", "ˈmaxən"
    ),
    "sehen": _v("to see", "Ich sehe einen Vogel.", "I see a bird.", "A1"),
    "sprechen": _v("to speak", "Er spricht drei Sprachen.", "He speaks three languages.", "A1"),
    "essen": _v("to eat", "Wir essen um sieben Uhr.", "We eat at seven o'clock.", "A1"),
    "trinken": _v("to drink", "Sie trinkt gern Tee.", "She likes to drink tea.", "A1"),
    "lesen": _v("to read", "Ich lese jeden Abend.", "I read every evening.", "A1"),
    "schreiben": _v("to write", "Er schreibt einen Brief.", "He is writing a letter.", "A1"),
    "kaufen": _v("to buy", "Ich kaufe frisches Obst.", "I buy fresh fruit.", "A1"),
    "verkaufen": _v("to sell", "Sie verkauft ihr altes Auto.", "She is selling her old car.", "A2"),
    "arbeiten": _v("to work", "Ich arbeite von zu Hause.", "I work from home.", "A1"),
    "lernen": _v(
        "to learn", "Wir lernen Deutsch zusammen.", "We are learning German together.", "A1"
    ),
    "spielen": _v(
        "to play", "Die Kinder spielen im Garten.", "The children are playing in the garden.", "A1"
    ),
    "wohnen": _v("to live / reside", "Ich wohne in Berlin.", "I live in Berlin.", "A1"),
    "leben": _v(
        "to live / be alive",
        "Meine Großeltern leben noch.",
        "My grandparents are still alive.",
        "A2",
    ),
    "lieben": _v("to love", "Ich liebe meine Familie.", "I love my family.", "A1"),
    "brauchen": _v("to need", "Ich brauche mehr Zeit.", "I need more time.", "A1"),
    "suchen": _v(
        "to search / look for", "Er sucht seinen Schlüssel.", "He is looking for his key.", "A1"
    ),
    "finden": _v(
        "to find", "Ich finde das Buch interessant.", "I find the book interesting.", "A1"
    ),
    "öffnen": _v("to open", "Bitte öffne das Fenster.", "Please open the window.", "A1"),
    "schließen": _v(
        "to close", "Sie schließt die Tür leise.", "She closes the door quietly.", "A2"
    ),
    "helfen": _v("to help", "Kannst du mir helfen?", "Can you help me?", "A1"),
    "fragen": _v("to ask", "Darf ich dich etwas fragen?", "May I ask you something?", "A1"),
    "antworten": _v(
        "to answer", "Er antwortet schnell auf die Frage.", "He answers the question quickly.", "A2"
    ),
    "denken": _v("to think", "Ich denke oft an dich.", "I often think of you.", "A2"),
    "wissen": _v(
        "to know (facts)", "Ich weiß die Antwort nicht.", "I don't know the answer.", "A1"
    ),
    "kennen": _v(
        "to know (people/things)", "Kennst du diesen Mann?", "Do you know this man?", "A1"
    ),
    "mögen": _v("to like", "Ich mag klassische Musik.", "I like classical music.", "A1"),
    "wollen": _v("to want", "Ich will nach Hause gehen.", "I want to go home.", "A1"),
    "können": _v(
        "to be able to / can", "Kannst du Deutsch sprechen?", "Can you speak German?", "A1"
    ),
    "müssen": _v("to have to / must", "Ich muss jetzt gehen.", "I have to go now.", "A1"),
    "sollen": _v("should", "Du sollst mehr schlafen.", "You should sleep more.", "A2"),
    "dürfen": _v(
        "to be allowed to / may", "Darf ich hier rauchen?", "Am I allowed to smoke here?", "A2"
    ),
    "fahren": _v(
        "to drive / travel",
        "Wir fahren morgen nach Köln.",
        "We are driving to Cologne tomorrow.",
        "A1",
    ),
    "fliegen": _v(
        "to fly", "Sie fliegt nächste Woche nach Rom.", "She is flying to Rome next week.", "A2"
    ),
    "laufen": _v(
        "to run / walk",
        "Er läuft jeden Morgen im Park.",
        "He runs in the park every morning.",
        "A1",
    ),
    "schlafen": _v("to sleep", "Das Baby schläft ruhig.", "The baby is sleeping peacefully.", "A1"),
    "aufstehen": _v("to get up", "Ich stehe um sechs Uhr auf.", "I get up at six o'clock.", "A1"),
    "warten": _v("to wait", "Wir warten auf den Bus.", "We are waiting for the bus.", "A1"),
    "geben": _v("to give", "Er gibt mir ein Geschenk.", "He gives me a gift.", "A1"),
    "nehmen": _v("to take", "Ich nehme den Zug um neun.", "I'm taking the train at nine.", "A1"),
    "verstehen": _v(
        "to understand", "Verstehst du diese Regel?", "Do you understand this rule?", "A2"
    ),
    # ── Adjectives ───────────────────────────────────────────────────────────
    "gut": _a("good", "Das Essen ist sehr gut.", "The food is very good.", "A1"),
    "schlecht": _a("bad", "Das Wetter ist heute schlecht.", "The weather is bad today.", "A1"),
    "groß": _a("big / tall", "Das Haus ist sehr groß.", "The house is very big.", "A1"),
    "klein": _a(
        "small", "Die Wohnung ist klein, aber gemütlich.", "The apartment is small but cozy.", "A1"
    ),
    "schnell": _a("fast", "Der Zug ist sehr schnell.", "The train is very fast.", "A1"),
    "langsam": _a("slow", "Er fährt sehr langsam.", "He drives very slowly.", "A1"),
    "alt": _a("old", "Mein Opa ist schon sehr alt.", "My grandpa is already very old.", "A1"),
    "neu": _a("new", "Ich habe ein neues Handy.", "I have a new phone.", "A1"),
    "jung": _a("young", "Sie ist noch sehr jung.", "She is still very young.", "A1"),
    "schön": _a("beautiful", "Der Park ist wirklich schön.", "The park is really beautiful.", "A1"),
    "teuer": _a(
        "expensive",
        "Das Restaurant ist mir zu teuer.",
        "The restaurant is too expensive for me.",
        "A1",
    ),
    "billig": _a("cheap", "Dieses Handy ist ziemlich billig.", "This phone is quite cheap.", "A2"),
    "warm": _a("warm", "Im Sommer ist es hier sehr warm.", "It's very warm here in summer.", "A1"),
    "kalt": _a("cold", "Der Kaffee ist schon kalt.", "The coffee is already cold.", "A1"),
    "lang": _a("long", "Der Weg zur Arbeit ist lang.", "The way to work is long.", "A1"),
    "kurz": _a("short", "Die Pause war zu kurz.", "The break was too short.", "A1"),
    "leicht": _a(
        "easy / light", "Die Prüfung war ziemlich leicht.", "The exam was quite easy.", "A1"
    ),
    "schwer": _a("difficult / heavy", "Diese Aufgabe ist schwer.", "This task is difficult.", "A1"),
    "glücklich": _a("happy", "Ich bin heute sehr glücklich.", "I am very happy today.", "A1"),
    "traurig": _a("sad", "Der Film hat mich traurig gemacht.", "The film made me sad.", "A2"),
    "müde": _a("tired", "Nach der Arbeit bin ich müde.", "After work I am tired.", "A1"),
    "wichtig": _a(
        "important",
        "Diese Entscheidung ist sehr wichtig.",
        "This decision is very important.",
        "A2",
    ),
    "interessant": _a(
        "interesting", "Das Buch ist wirklich interessant.", "The book is really interesting.", "A2"
    ),
    "langweilig": _a("boring", "Der Vortrag war langweilig.", "The lecture was boring.", "A2"),
    "freundlich": _a(
        "friendly",
        "Die Verkäuferin war sehr freundlich.",
        "The saleswoman was very friendly.",
        "A1",
    ),
}

# Case-insensitive lookup index → canonical (correctly-cased) key.
_INDEX: dict[str, str] = {k.lower(): k for k in CURATED}

_ARTICLES = {"der", "die", "das"}


def _normalize_lemma(raw: str) -> str:
    """Strip a leading article ('der Tisch' → 'Tisch') so lookups are article-agnostic."""
    s = (raw or "").strip()
    head, _, rest = s.partition(" ")
    if rest and head.lower() in _ARTICLES:
        return rest.strip()
    return s


def _from_curated(canon: str, *, gloss_langs: tuple[str, ...]) -> dict[str, Any]:
    entry = CURATED[canon]
    meanings = [m for m in entry["meanings"] if m["lang"] in gloss_langs] or entry["meanings"]
    display_lemma = f"{entry['article']} {canon}" if entry["article"] else canon
    return {
        "lemma": display_lemma,
        "pos": entry["pos"],
        "article": entry["article"],
        "plural": entry["plural"],
        "ipa": entry["ipa"],
        "audio_url": f"/api/v1/tts?text={quote(canon)}",
        "meanings": meanings,
        "examples": entry["examples"],
        "cefr_level": entry["cefr_level"],
        "source": "dictionary",
    }


# ── LLM fallback for words not in the curated table ────────────────────────────

_LLM_LOOKUP_SYSTEM = """\
You are a precise German dictionary. Return STRICT JSON only — no prose, no markdown \
fences — describing the German word the learner gives you.

Shape:
{"pos": "noun|verb|adjective|adverb|other", "article": "der|die|das" or null, \
"plural": "string or null", "ipa": "string or null", \
"meanings": [{"lang": "en", "text": "..."}], \
"examples": [{"de": "...", "en": "..."}], "cefr_level": "A1|A2|B1|B2|C1"}

`article` must be null unless pos is "noun". If you are not confident about a noun's \
gender or plural, use null rather than guessing — a wrong gender taught as fact is \
worse than admitting uncertainty.
"""


async def _from_llm(
    db: AsyncSession,
    word: str,
    *,
    gloss_langs: tuple[str, ...],
    user_id: Any | None,
) -> dict[str, Any]:
    messages = [
        SystemMessage(content=_LLM_LOOKUP_SYSTEM),
        HumanMessage(content=f"Word: {word}\nGloss languages: {', '.join(gloss_langs)}"),
    ]
    result = await ai_router.complete(
        db, task_type=TaskType.TRANSLATE, messages=messages, user_id=user_id
    )
    try:
        data = parse_json_object(result.text)
    except ValueError as exc:
        log.warning("dictionary_llm_bad_json", word=word, error=str(exc))
        raise UpstreamError("The dictionary fallback returned malformed JSON.") from exc

    article = data.get("article") or None
    display_lemma = f"{article} {word}" if article else word
    return {
        "lemma": display_lemma,
        "pos": data.get("pos"),
        "article": article,
        "plural": data.get("plural"),
        "ipa": data.get("ipa"),
        "audio_url": f"/api/v1/tts?text={quote(word)}",
        "meanings": data.get("meanings") or [],
        "examples": data.get("examples") or [],
        "cefr_level": data.get("cefr_level"),
        "source": "llm",
    }


async def lookup(
    db: AsyncSession,
    lemma: str,
    *,
    gloss_langs: tuple[str, ...] = ("en",),
    user_id: Any | None = None,
) -> dict[str, Any]:
    """Look up a German word (API_CONTRACT.md §3 `lookup-word` response shape).

    Curated hit → ``source="dictionary"`` (ground truth, hand-verified). Miss →
    one call to the AI Router asking for strict JSON → ``source="llm"``. The
    `source` field is deliberate provenance: the UI must never present an
    LLM-guessed noun gender with the same authority as a verified one.
    """
    key = _normalize_lemma(lemma)
    canon = _INDEX.get(key.lower())
    if canon is not None:
        return _from_curated(canon, gloss_langs=gloss_langs)
    return await _from_llm(db, key, gloss_langs=gloss_langs, user_id=user_id)
