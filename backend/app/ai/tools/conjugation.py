"""Deterministic German verb conjugation.

Why a rule engine instead of asking the LLM: a wrong conjugation taught confidently
is the single worst failure mode for a language tutor. Conjugation is a *solved*,
rule-governed problem for weak verbs, and a finite lookup for strong/irregular ones —
so we compute it and the model reports it. No hallucinated paradigms.

Coverage: Präsens, Präteritum, Perfekt, Futur I, Konjunktiv II, Imperativ.
Irregular verbs are the high-frequency set a learner meets from A1 to B2.
"""

from __future__ import annotations

from typing import Literal, TypedDict

Tense = Literal["praesens", "praeteritum", "perfekt", "futur1", "konjunktiv2", "imperativ"]

PERSONS = ("ich", "du", "er_sie_es", "wir", "ihr", "sie_Sie")


class Conjugation(TypedDict):
    verb: str
    tense: str
    is_irregular: bool
    auxiliary: str
    forms: dict[str, str]
    source: str
    note: str | None


class _Irregular(TypedDict, total=False):
    praesens: dict[str, str]      # only the forms that deviate
    praet_stem: str               # Präteritum stem (ich/er take no ending)
    praet: dict[str, str]         # full override when the pattern differs (sein)
    participle: str
    aux: Literal["haben", "sein"]
    k2_stem: str                  # Konjunktiv II stem, e.g. wär-, hätt-, ging-
    separable: str                # separable prefix, e.g. "auf" in aufstehen


# ── Irregular / strong verb table ─────────────────────────────────────────────

IRREGULAR: dict[str, _Irregular] = {
    "sein": {
        "praesens": {"ich": "bin", "du": "bist", "er_sie_es": "ist", "wir": "sind", "ihr": "seid", "sie_Sie": "sind"},
        "praet": {"ich": "war", "du": "warst", "er_sie_es": "war", "wir": "waren", "ihr": "wart", "sie_Sie": "waren"},
        "participle": "gewesen", "aux": "sein", "k2_stem": "wär",
    },
    "haben": {
        "praesens": {"du": "hast", "er_sie_es": "hat"},
        "praet_stem": "hatt", "participle": "gehabt", "aux": "haben", "k2_stem": "hätt",
    },
    "werden": {
        "praesens": {"ich": "werde", "du": "wirst", "er_sie_es": "wird"},
        "praet_stem": "wurd", "participle": "geworden", "aux": "sein", "k2_stem": "würd",
    },
    "gehen": {"praet_stem": "ging", "participle": "gegangen", "aux": "sein", "k2_stem": "ging"},
    "kommen": {"praet_stem": "kam", "participle": "gekommen", "aux": "sein", "k2_stem": "käm"},
    "sehen": {"praesens": {"du": "siehst", "er_sie_es": "sieht"}, "praet_stem": "sah", "participle": "gesehen", "aux": "haben", "k2_stem": "säh"},
    "geben": {"praesens": {"du": "gibst", "er_sie_es": "gibt"}, "praet_stem": "gab", "participle": "gegeben", "aux": "haben", "k2_stem": "gäb"},
    "nehmen": {"praesens": {"du": "nimmst", "er_sie_es": "nimmt"}, "praet_stem": "nahm", "participle": "genommen", "aux": "haben", "k2_stem": "nähm"},
    "sprechen": {"praesens": {"du": "sprichst", "er_sie_es": "spricht"}, "praet_stem": "sprach", "participle": "gesprochen", "aux": "haben", "k2_stem": "spräch"},
    "essen": {"praesens": {"du": "isst", "er_sie_es": "isst"}, "praet_stem": "aß", "participle": "gegessen", "aux": "haben", "k2_stem": "äß"},
    "trinken": {"praet_stem": "trank", "participle": "getrunken", "aux": "haben", "k2_stem": "tränk"},
    "fahren": {"praesens": {"du": "fährst", "er_sie_es": "fährt"}, "praet_stem": "fuhr", "participle": "gefahren", "aux": "sein", "k2_stem": "führ"},
    "laufen": {"praesens": {"du": "läufst", "er_sie_es": "läuft"}, "praet_stem": "lief", "participle": "gelaufen", "aux": "sein", "k2_stem": "lief"},
    "lesen": {"praesens": {"du": "liest", "er_sie_es": "liest"}, "praet_stem": "las", "participle": "gelesen", "aux": "haben", "k2_stem": "läs"},
    "schlafen": {"praesens": {"du": "schläfst", "er_sie_es": "schläft"}, "praet_stem": "schlief", "participle": "geschlafen", "aux": "haben", "k2_stem": "schlief"},
    "schreiben": {"praet_stem": "schrieb", "participle": "geschrieben", "aux": "haben", "k2_stem": "schrieb"},
    "bleiben": {"praet_stem": "blieb", "participle": "geblieben", "aux": "sein", "k2_stem": "blieb"},
    "finden": {"praet_stem": "fand", "participle": "gefunden", "aux": "haben", "k2_stem": "fänd"},
    "stehen": {"praet_stem": "stand", "participle": "gestanden", "aux": "haben", "k2_stem": "ständ"},
    "helfen": {"praesens": {"du": "hilfst", "er_sie_es": "hilft"}, "praet_stem": "half", "participle": "geholfen", "aux": "haben", "k2_stem": "hülf"},
    "heißen": {"praesens": {"du": "heißt", "er_sie_es": "heißt"}, "praet_stem": "hieß", "participle": "geheißen", "aux": "haben", "k2_stem": "hieß"},
    "tun": {"praesens": {"ich": "tue", "du": "tust", "er_sie_es": "tut", "wir": "tun", "ihr": "tut", "sie_Sie": "tun"}, "praet_stem": "tat", "participle": "getan", "aux": "haben", "k2_stem": "tät"},
    "wissen": {"praesens": {"ich": "weiß", "du": "weißt", "er_sie_es": "weiß"}, "praet_stem": "wusst", "participle": "gewusst", "aux": "haben", "k2_stem": "wüsst"},
    # Modals — irregular in the singular present.
    "können": {"praesens": {"ich": "kann", "du": "kannst", "er_sie_es": "kann"}, "praet_stem": "konnt", "participle": "gekonnt", "aux": "haben", "k2_stem": "könnt"},
    "müssen": {"praesens": {"ich": "muss", "du": "musst", "er_sie_es": "muss"}, "praet_stem": "musst", "participle": "gemusst", "aux": "haben", "k2_stem": "müsst"},
    "wollen": {"praesens": {"ich": "will", "du": "willst", "er_sie_es": "will"}, "praet_stem": "wollt", "participle": "gewollt", "aux": "haben", "k2_stem": "wollt"},
    "sollen": {"praesens": {"ich": "soll", "du": "sollst", "er_sie_es": "soll"}, "praet_stem": "sollt", "participle": "gesollt", "aux": "haben", "k2_stem": "sollt"},
    "dürfen": {"praesens": {"ich": "darf", "du": "darfst", "er_sie_es": "darf"}, "praet_stem": "durft", "participle": "gedurft", "aux": "haben", "k2_stem": "dürft"},
    "mögen": {"praesens": {"ich": "mag", "du": "magst", "er_sie_es": "mag"}, "praet_stem": "mocht", "participle": "gemocht", "aux": "haben", "k2_stem": "möcht"},
}

# Verbs of motion / change of state take "sein" in the Perfekt.
_SEIN_VERBS = {
    "gehen", "kommen", "fahren", "laufen", "fliegen", "reisen", "bleiben",
    "werden", "sein", "steigen", "fallen", "wachsen", "sterben", "passieren",
    "geschehen", "aufstehen", "einschlafen", "ankommen", "abfahren",
}

_SEPARABLE_PREFIXES = (
    "auf", "aus", "an", "ab", "ein", "mit", "nach", "vor", "zu", "zurück",
    "zusammen", "weg", "her", "hin", "los", "fest", "frei",
)

_INSEPARABLE_PREFIXES = ("be", "ge", "er", "ver", "zer", "ent", "emp", "miss")


def _split_separable(verb: str) -> tuple[str, str]:
    """('aufstehen') → ('auf', 'stehen'); ('gehen') → ('', 'gehen')."""
    for p in sorted(_SEPARABLE_PREFIXES, key=len, reverse=True):
        rest = verb[len(p):]
        if verb.startswith(p) and len(rest) >= 4 and (rest in IRREGULAR or rest.endswith(("en", "ern", "eln"))):
            return p, rest
    return "", verb


def _stem(infinitive: str) -> str:
    for suffix in ("en", "n"):
        if infinitive.endswith(suffix):
            return infinitive[: -len(suffix)]
    return infinitive


def _needs_e(stem: str) -> bool:
    """arbeiten → du arbeitest: -d/-t (and some -m/-n clusters) need a linking e."""
    return stem.endswith(("d", "t")) or (
        len(stem) >= 2 and stem[-1] in "mn" and stem[-2] not in "aeiouälmnr"
    )


def _sibilant(stem: str) -> bool:
    return stem.endswith(("s", "ß", "z", "x", "sch"))


def _praesens_regular(stem: str) -> dict[str, str]:
    e = "e" if _needs_e(stem) else ""
    du = f"{stem}{e}st" if not (_sibilant(stem) and not e) else f"{stem}est" if _needs_e(stem) else f"{stem}t"
    # reisen → du reist (sibilant absorbs the s); arbeiten → du arbeitest
    if _sibilant(stem) and not _needs_e(stem):
        du = f"{stem}t"
    return {
        "ich": f"{stem}e",
        "du": du,
        "er_sie_es": f"{stem}{e}t",
        "wir": f"{stem}en",
        "ihr": f"{stem}{e}t",
        "sie_Sie": f"{stem}en",
    }


def _praeteritum_regular(stem: str) -> dict[str, str]:
    e = "e" if _needs_e(stem) else ""
    base = f"{stem}{e}t"
    return {
        "ich": f"{base}e", "du": f"{base}est", "er_sie_es": f"{base}e",
        "wir": f"{base}en", "ihr": f"{base}et", "sie_Sie": f"{base}en",
    }


def _praeteritum_strong(praet_stem: str) -> dict[str, str]:
    # ich/er take no ending; the plural is always -en (ging → gingen, war → waren).
    e = "e" if _needs_e(praet_stem) else ""
    return {
        "ich": praet_stem,
        "du": f"{praet_stem}{e}st",
        "er_sie_es": praet_stem,
        "wir": f"{praet_stem}en",
        "ihr": f"{praet_stem}{e}t",
        "sie_Sie": f"{praet_stem}en",
    }


def _participle(verb: str, prefix: str, irr: _Irregular | None) -> str:
    if irr and irr.get("participle"):
        base = irr["participle"]
        return f"{prefix}{base}" if prefix else base
    stem = _stem(verb)
    if verb.startswith(_INSEPARABLE_PREFIXES) or verb.endswith("ieren"):
        core = f"{stem}{'et' if _needs_e(stem) else 't'}"
    else:
        core = f"ge{stem}{'et' if _needs_e(stem) else 't'}"
    return f"{prefix}{core}" if prefix else core


def conjugate(verb: str, tense: Tense = "praesens") -> Conjugation:
    """Conjugate `verb` in `tense`. Raises ValueError on empty input."""
    raw = (verb or "").strip().lower()
    if not raw:
        raise ValueError("verb must not be empty")
    if not raw.endswith(("en", "n")):
        raise ValueError(
            f"'{verb}' doesn't look like a German infinitive (expected an -en/-n ending)."
        )

    prefix, core = _split_separable(raw)
    irr = IRREGULAR.get(core) or None
    is_irregular = irr is not None
    stem = _stem(core)
    # The FULL verb decides the auxiliary before the base verb does: "aufstehen"
    # takes sein even though "stehen" takes haben.
    if raw in _SEIN_VERBS:
        aux = "sein"
    elif irr and irr.get("aux"):
        aux = irr["aux"]
    else:
        aux = "sein" if core in _SEIN_VERBS else "haben"
    note: str | None = None

    if prefix:
        note = (
            f"Separable verb: the prefix '{prefix}' goes to the end of the clause in "
            f"main clauses — e.g. 'Ich stehe früh {prefix}.'"
        )

    def _detach(forms: dict[str, str]) -> dict[str, str]:
        """Separable prefix detaches in finite tenses: 'ich stehe … auf'."""
        return {p: f"{f} … {prefix}" for p, f in forms.items()} if prefix else forms

    if tense == "praesens":
        base = _praesens_regular(stem)
        if irr and irr.get("praesens"):
            base = {**base, **irr["praesens"]}
        forms = _detach(base)

    elif tense == "praeteritum":
        if irr and irr.get("praet"):
            base = dict(irr["praet"])
        elif irr and irr.get("praet_stem"):
            base = _praeteritum_strong(irr["praet_stem"])
        else:
            base = _praeteritum_regular(stem)
        forms = _detach(base)

    elif tense == "perfekt":
        part = _participle(core, prefix, irr)
        aux_forms = (
            conjugate("haben", "praesens")["forms"]
            if aux == "haben"
            else conjugate("sein", "praesens")["forms"]
        )
        forms = {p: f"{aux_forms[p]} {part}" for p in PERSONS}
        note = f"Perfekt uses '{aux}' + past participle '{part}'." + (f" {note}" if note else "")

    elif tense == "futur1":
        w = conjugate("werden", "praesens")["forms"]
        forms = {p: f"{w[p]} {raw}" for p in PERSONS}
        note = "Futur I = 'werden' + infinitive at the end of the clause."

    elif tense == "konjunktiv2":
        k2 = (irr or {}).get("k2_stem")
        if k2:
            forms = {
                "ich": f"{k2}e", "du": f"{k2}est", "er_sie_es": f"{k2}e",
                "wir": f"{k2}en", "ihr": f"{k2}et", "sie_Sie": f"{k2}en",
            }
            forms = _detach(forms)
            note = (
                "Strong verbs form Konjunktiv II from the Präteritum stem with an umlaut. "
                "In everyday speech 'würde + infinitive' is more common."
            )
        else:
            wuerde = {"ich": "würde", "du": "würdest", "er_sie_es": "würde",
                      "wir": "würden", "ihr": "würdet", "sie_Sie": "würden"}
            forms = {p: f"{wuerde[p]} {raw}" for p in PERSONS}
            note = "Weak verbs use 'würde' + infinitive for Konjunktiv II."

    elif tense == "imperativ":
        pres = _praesens_regular(stem)
        if irr and irr.get("praesens"):
            pres = {**pres, **irr["praesens"]}
        # du-imperative: present du-form minus -st; strong e→i verbs keep the shift.
        du_form = pres["du"].removesuffix("st") or stem
        du_imp = du_form if (irr and irr.get("praesens", {}).get("du")) else (
            f"{stem}e" if _needs_e(stem) else stem
        )
        forms = {
            "du": f"{du_imp}{f' … {prefix}' if prefix else ''}!",
            "ihr": f"{pres['ihr']}{f' … {prefix}' if prefix else ''}!",
            # Sie-imperative is the plain infinitive + "Sie": "gehen Sie!"
            "Sie": f"{core} Sie{f' … {prefix}' if prefix else ''}!",
        }
        note = "Imperative exists only for du / ihr / Sie."

    else:  # pragma: no cover - guarded by Pydantic upstream
        raise ValueError(f"unsupported tense: {tense}")

    return Conjugation(
        verb=raw,
        tense=tense,
        is_irregular=is_irregular,
        auxiliary=aux,
        forms=forms,
        source="rule_engine",
        note=note,
    )
