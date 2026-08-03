"""Deterministic Spanish verb conjugation.

Same thesis as the German engine: a wrong conjugation taught confidently is the
worst failure mode a language tutor has, and conjugation is a solved, rule-governed
problem. So we compute it and the model reports it.

Coverage: presente, pretérito indefinido, imperfecto, futuro, condicional,
presente de subjuntivo, plus participle and gerund. Those are the tenses a learner
meets from A1 to B2; anything beyond (pluscuamperfecto, imperfecto de subjuntivo)
is composed from the participle or left to a later pass rather than guessed at.

## What is genuinely hard in Spanish, and how it is handled

- **Stem changes** (e→ie, o→ue, e→i) hit the four "boot" persons — everything but
  nosotros/vosotros. They are listed per verb rather than derived, because which
  verbs stem-change is lexical, not predictable from spelling: `contar`→cuento
  but `montar`→monto.
- **Strong preterites** take a different, UNSTRESSED ending set (-e, -iste, -o…
  with no accents), which is why `tuve` has no accent while regular `hablé` does.
  Getting this wrong is the classic learner error, so the ending sets are
  separate constants rather than one table with exceptions.
- **`decir`-type preterites** end in -j and take -eron, not -ieron (`dijeron`,
  never `dijieron`).
- **Orthographic changes** (c→qu, g→gu, z→c) preserve the SOUND across an ending
  change: `buscar`→`busqué`, not `buscé`. Sound-preserving spelling is not
  optional in Spanish and a learner will be marked wrong for it.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

Tense = Literal[
    "presente",
    "preterito",
    "imperfecto",
    "futuro",
    "condicional",
    "subjuntivo_presente",
]

PERSONS = ("yo", "tu", "el_ella_usted", "nosotros", "vosotros", "ellos_ellas_ustedes")

# The four "boot" persons a stem change applies to — everything except
# nosotros/vosotros, which keep the unstressed infinitive stem.
_BOOT = ("yo", "tu", "el_ella_usted", "ellos_ellas_ustedes")


class Conjugation(TypedDict):
    verb: str
    tense: str
    is_irregular: bool
    forms: dict[str, str]
    participle: str
    gerund: str
    source: str
    note: str | None


class _Irregular(TypedDict, total=False):
    presente: dict[str, str]        # only the forms that deviate
    stem_change: tuple[str, str]    # (from, to) applied to the boot persons
    pret_stem: str                  # strong preterite stem — takes UNSTRESSED endings
    pret: dict[str, str]            # full override where no stem works (ser/ir)
    fut_stem: str                   # irregular future/conditional stem
    imperfecto: dict[str, str]      # full override (only ser, ir, ver)
    subj_stem: str                  # subjunctive stem when it is not the yo-form
    participle: str
    gerund: str


# ── Endings ───────────────────────────────────────────────────────────────────

_PRESENTE = {
    "ar": ("o", "as", "a", "amos", "áis", "an"),
    "er": ("o", "es", "e", "emos", "éis", "en"),
    "ir": ("o", "es", "e", "imos", "ís", "en"),
}

_PRETERITO = {
    "ar": ("é", "aste", "ó", "amos", "asteis", "aron"),
    "er": ("í", "iste", "ió", "imos", "isteis", "ieron"),
    "ir": ("í", "iste", "ió", "imos", "isteis", "ieron"),
}

# Strong preterites are UNSTRESSED — no accent on yo/él. `tuve`, not `tuvé`.
# This is the single most common place learners (and language models) go wrong.
_PRETERITO_STRONG = ("e", "iste", "o", "imos", "isteis", "ieron")

_IMPERFECTO = {
    "ar": ("aba", "abas", "aba", "ábamos", "abais", "aban"),
    "er": ("ía", "ías", "ía", "íamos", "íais", "ían"),
    "ir": ("ía", "ías", "ía", "íamos", "íais", "ían"),
}

# Future and conditional attach to the WHOLE infinitive, not a stem — which is
# why they share one ending set across all three conjugations.
_FUTURO = ("é", "ás", "á", "emos", "éis", "án")
_CONDICIONAL = ("ía", "ías", "ía", "íamos", "íais", "ían")

# Subjunctive "flips" the vowel: -ar verbs take e-endings and -er/-ir take a.
_SUBJUNTIVO = {
    "ar": ("e", "es", "e", "emos", "éis", "en"),
    "er": ("a", "as", "a", "amos", "áis", "an"),
    "ir": ("a", "as", "a", "amos", "áis", "an"),
}


# ── Irregular table: the high-frequency set a learner meets A1–B2 ─────────────

IRREGULAR: dict[str, _Irregular] = {
    "ser": {
        "presente": dict(
            zip(PERSONS, ("soy", "eres", "es", "somos", "sois", "son"), strict=True)
        ),
        "pret": dict(
            zip(PERSONS, ("fui", "fuiste", "fue", "fuimos", "fuisteis", "fueron"), strict=True)
        ),
        "imperfecto": dict(
            zip(PERSONS, ("era", "eras", "era", "éramos", "erais", "eran"), strict=True)
        ),
        "subj_stem": "se",
    },
    "estar": {
        "presente": dict(
            zip(PERSONS, ("estoy", "estás", "está", "estamos", "estáis", "están"), strict=True)
        ),
        "pret_stem": "estuv",
    },
    "ir": {
        "presente": dict(zip(PERSONS, ("voy", "vas", "va", "vamos", "vais", "van"), strict=True)),
        # `ir` and `ser` share a preterite — a genuine syncretism, not a typo.
        "pret": dict(
            zip(PERSONS, ("fui", "fuiste", "fue", "fuimos", "fuisteis", "fueron"), strict=True)
        ),
        "imperfecto": dict(
            zip(PERSONS, ("iba", "ibas", "iba", "íbamos", "ibais", "iban"), strict=True)
        ),
        "subj_stem": "vay",
        "gerund": "yendo",
    },
    "haber": {
        "presente": dict(zip(PERSONS, ("he", "has", "ha", "hemos", "habéis", "han"), strict=True)),
        "pret_stem": "hub",
        "fut_stem": "habr",
        "subj_stem": "hay",
    },
    "tener": {
        "presente": {"yo": "tengo"},
        "stem_change": ("e", "ie"),
        "pret_stem": "tuv",
        "fut_stem": "tendr",
        "subj_stem": "teng",
    },
    "hacer": {
        "presente": {"yo": "hago"},
        "pret_stem": "hic",  # hiz- before -o, handled in _strong_preterite
        "fut_stem": "har",
        "subj_stem": "hag",
        "participle": "hecho",
    },
    "poder": {
        "stem_change": ("o", "ue"),
        "pret_stem": "pud",
        "fut_stem": "podr",
        "gerund": "pudiendo",
    },
    "decir": {
        "presente": {"yo": "digo"},
        "stem_change": ("e", "i"),
        "pret_stem": "dij",  # takes -eron, not -ieron
        "fut_stem": "dir",
        "subj_stem": "dig",
        "participle": "dicho",
        "gerund": "diciendo",
    },
    "ver": {
        "presente": {"yo": "veo", "vosotros": "veis"},
        "imperfecto": dict(
            zip(PERSONS, ("veía", "veías", "veía", "veíamos", "veíais", "veían"), strict=True)
        ),
        "subj_stem": "ve",
        "participle": "visto",
    },
    "dar": {
        "presente": {"yo": "doy", "vosotros": "dais"},
        "pret": dict(
            zip(PERSONS, ("di", "diste", "dio", "dimos", "disteis", "dieron"), strict=True)
        ),
        "subj_stem": "d",
    },
    "saber": {
        "presente": {"yo": "sé"},
        "pret_stem": "sup",
        "fut_stem": "sabr",
        "subj_stem": "sep",
    },
    "querer": {
        "stem_change": ("e", "ie"),
        "pret_stem": "quis",
        "fut_stem": "querr",
    },
    "venir": {
        "presente": {"yo": "vengo"},
        "stem_change": ("e", "ie"),
        "pret_stem": "vin",
        "fut_stem": "vendr",
        "subj_stem": "veng",
        "gerund": "viniendo",
    },
    "poner": {
        "presente": {"yo": "pongo"},
        "pret_stem": "pus",
        "fut_stem": "pondr",
        "subj_stem": "pong",
        "participle": "puesto",
    },
    "salir": {
        "presente": {"yo": "salgo"},
        "fut_stem": "saldr",
        "subj_stem": "salg",
    },
    "pedir": {"stem_change": ("e", "i"), "gerund": "pidiendo"},
    "dormir": {"stem_change": ("o", "ue"), "gerund": "durmiendo"},
    "pensar": {"stem_change": ("e", "ie")},
    "volver": {"stem_change": ("o", "ue"), "participle": "vuelto"},
    "empezar": {"stem_change": ("e", "ie")},
    "encontrar": {"stem_change": ("o", "ue")},
    "escribir": {"participle": "escrito"},
    "abrir": {"participle": "abierto"},
    "leer": {"gerund": "leyendo"},
    "oír": {
        "presente": dict(
            zip(PERSONS, ("oigo", "oyes", "oye", "oímos", "oís", "oyen"), strict=True)
        ),
        "pret": dict(
            zip(PERSONS, ("oí", "oíste", "oyó", "oímos", "oísteis", "oyeron"), strict=True)
        ),
        "subj_stem": "oig",
        "participle": "oído",
        "gerund": "oyendo",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

# `*` not `+`, because `ir` (to go) is a complete infinitive on its own — the one
# two-letter verb in the language. `ar` and `er` are not verbs, so they are
# rejected explicitly rather than by making the pattern stricter and losing `ir`.
# `ír` as well as `ir`: oír, reír, sonreír carry the accent in the infinitive
# itself. The class is normalised below, so downstream tables stay keyed on the
# three unaccented classes.
_INFINITIVE = re.compile(r"^[a-záéíóúüñ]*(ar|er|ir|ír)$")
_NOT_VERBS = frozenset({"ar", "er"})


def _split(verb: str) -> tuple[str, str]:
    """(stem, conjugation-class) for an infinitive.

    The class is de-accented: `oír` is an -ir verb whose infinitive happens to be
    written with an accent, so every ending table stays keyed on ar/er/ir.
    """
    return verb[:-2], verb[-2:].replace("í", "i")


def _apply_stem_change(stem: str, change: tuple[str, str], person: str) -> str:
    """e→ie / o→ue / e→i on the boot persons only.

    Replaces the LAST occurrence of the vowel, not the first: `empezar` is
    `empiezo`, so the change lands on the stressed syllable rather than the one
    that happens to come first (`*iempezo`).
    """
    if person not in _BOOT:
        return stem
    src, dst = change
    idx = stem.rfind(src)
    if idx == -1:
        return stem
    return stem[:idx] + dst + stem[idx + 1 :]


def _orthographic(stem: str, ending: str) -> str:
    """Preserve the stem's SOUND across an ending that would change it.

    buscar → busqué (not *buscé: `ce` would be /θe/, not /ke/)
    llegar → llegué (not *llegé: `ge` would be /xe/)
    empezar → empecé (z never precedes e in Spanish orthography)

    This is not cosmetic — a learner writing *buscé is marked wrong.
    """
    if not ending or ending[0] not in "eéií":
        return stem
    if stem.endswith("c"):
        return stem[:-1] + "qu"
    if stem.endswith("g"):
        return stem[:-1] + "gu"
    if stem.endswith("z"):
        return stem[:-1] + "c"
    return stem


def _strong_preterite(stem: str) -> dict[str, str]:
    """Strong preterite: unstressed endings, and -eron after a j-stem."""
    forms: dict[str, str] = {}
    for person, ending in zip(PERSONS, _PRETERITO_STRONG, strict=True):
        s = stem
        # hacer: hic- → hiz- before -o, so the /θ/ survives (`hizo`, not *`hico`).
        if stem == "hic" and ending == "o":
            s = "hiz"
        # dij-/traj-/dedu-j- take -eron: `dijeron`, never *`dijieron`.
        if stem.endswith("j") and ending == "ieron":
            ending = "eron"
        forms[person] = s + ending
    return forms


def participle(verb: str) -> str:
    irr = IRREGULAR.get(verb, {})
    if "participle" in irr:
        return irr["participle"]
    stem, cls = _split(verb)
    if cls == "ar":
        return stem + "ado"
    # An -er/-ir stem ending in a vowel takes an ACCENTED í, because the i would
    # otherwise form a diphthong with it and the stress would move:
    # leer → leído, caer → caído, oír → oído. Writing *leido is a spelling error,
    # not a variant.
    if stem and stem[-1] in "aeo":
        return stem + "ído"
    return stem + "ido"


def gerund(verb: str) -> str:
    irr = IRREGULAR.get(verb, {})
    if "gerund" in irr:
        return irr["gerund"]
    stem, cls = _split(verb)
    return stem + ("ando" if cls == "ar" else "iendo")


# ── Public entry point ────────────────────────────────────────────────────────


def conjugate(verb: str, tense: Tense = "presente") -> Conjugation:
    """Conjugate `verb` in `tense`. Raises ValueError on non-infinitives."""
    raw = (verb or "").strip().lower()
    if not raw:
        raise ValueError("verb must not be empty")
    if not _INFINITIVE.match(raw) or raw in _NOT_VERBS:
        raise ValueError(
            f"'{verb}' doesn't look like a Spanish infinitive (expected an -ar/-er/-ir ending)."
        )

    stem, cls = _split(raw)
    irr = IRREGULAR.get(raw) or None
    is_irregular = irr is not None
    note: str | None = None
    forms: dict[str, str] = {}

    if tense == "presente":
        for person, ending in zip(PERSONS, _PRESENTE[cls], strict=True):
            s = stem
            if irr and "stem_change" in irr:
                s = _apply_stem_change(s, irr["stem_change"], person)
            forms[person] = s + ending
        if irr and "presente" in irr:
            forms.update(irr["presente"])

    elif tense == "preterito":
        if irr and "pret" in irr:
            forms = dict(irr["pret"])
            note = "Irregular preterite — learn it as a set."
        elif irr and "pret_stem" in irr:
            forms = _strong_preterite(irr["pret_stem"])
            note = "Strong preterite: endings carry no accent (tuve, not *tuvé)."
        else:
            for person, ending in zip(PERSONS, _PRETERITO[cls], strict=True):
                forms[person] = _orthographic(stem, ending) + ending

    elif tense == "imperfecto":
        if irr and "imperfecto" in irr:
            forms = dict(irr["imperfecto"])
            note = "Only ser, ir and ver are irregular in the imperfect."
        else:
            for person, ending in zip(PERSONS, _IMPERFECTO[cls], strict=True):
                forms[person] = stem + ending

    elif tense in ("futuro", "condicional"):
        endings = _FUTURO if tense == "futuro" else _CONDICIONAL
        # The base is the whole infinitive unless the verb has an irregular stem —
        # and the SAME stem serves both tenses, which is why they share a branch.
        base = irr["fut_stem"] if (irr and "fut_stem" in irr) else raw
        for person, ending in zip(PERSONS, endings, strict=True):
            forms[person] = base + ending
        if irr and "fut_stem" in irr:
            note = "Irregular stem, shared by the future and the conditional."

    elif tense == "subjuntivo_presente":
        # Built from the yo-form of the present, which is why `tener` gives
        # `tenga` — the irregularity is inherited rather than re-learned.
        if irr and "subj_stem" in irr:
            base = irr["subj_stem"]
        elif irr and "presente" in irr and "yo" in irr["presente"]:
            base = irr["presente"]["yo"].removesuffix("o")
        else:
            base = stem
        for person, ending in zip(PERSONS, _SUBJUNTIVO[cls], strict=True):
            s = base
            # Stem changes still apply on the boot persons unless an explicit
            # subjunctive stem already encodes them.
            if irr and "stem_change" in irr and "subj_stem" not in irr:
                s = _apply_stem_change(s, irr["stem_change"], person)
            forms[person] = _orthographic(s, ending) + ending

    else:  # pragma: no cover - guarded by Pydantic upstream
        raise ValueError(f"unsupported tense: {tense}")

    return Conjugation(
        verb=raw,
        tense=tense,
        is_irregular=is_irregular,
        forms=forms,
        participle=participle(raw),
        gerund=gerund(raw),
        source="rule_engine",
        note=note,
    )
