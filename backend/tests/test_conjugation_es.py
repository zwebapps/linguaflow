"""Spanish conjugation.

These pin the places a rule engine — or a language model — actually goes wrong.
Regular `hablar` is not interesting; it is `tuve` without an accent, `hizo` not
*hico, `dijeron` not *dijieron, `busqué` not *buscé, and `leído` not *leido.

Every expected form here is a paradigm a learner would be marked against, which
is the point of computing them instead of asking the model: a confidently wrong
conjugation is the worst output a tutor can produce, because the learner has no
way to know.
"""

from __future__ import annotations

import pytest

from app.ai.tools.conjugation_es import PERSONS, conjugate, gerund, participle


def forms(verb: str, tense: str = "presente") -> dict[str, str]:
    return conjugate(verb, tense)["forms"]  # type: ignore[arg-type]


# ── Regular paradigms ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verb,expected",
    [
        ("hablar", ("hablo", "hablas", "habla", "hablamos", "habláis", "hablan")),
        ("comer", ("como", "comes", "come", "comemos", "coméis", "comen")),
        ("vivir", ("vivo", "vives", "vive", "vivimos", "vivís", "viven")),
    ],
)
def test_the_three_regular_classes_in_the_present(verb: str, expected: tuple[str, ...]) -> None:
    assert tuple(forms(verb)[p] for p in PERSONS) == expected


def test_every_tense_returns_all_six_persons() -> None:
    """A missing person is a silent gap in a paradigm a learner is memorising."""
    for tense in (
        "presente",
        "preterito",
        "imperfecto",
        "futuro",
        "condicional",
        "subjuntivo_presente",
    ):
        assert set(forms("hablar", tense)) == set(PERSONS), tense


def test_future_and_conditional_build_on_the_whole_infinitive() -> None:
    """Not the stem — `hablaré` keeps the -ar, unlike every other tense."""
    assert forms("hablar", "futuro")["yo"] == "hablaré"
    assert forms("comer", "condicional")["yo"] == "comería"


def test_the_subjunctive_flips_the_vowel() -> None:
    """-ar verbs take e-endings, -er/-ir take a. The commonest B1 confusion."""
    assert forms("hablar", "subjuntivo_presente")["yo"] == "hable"
    assert forms("comer", "subjuntivo_presente")["yo"] == "coma"


# ── Strong preterites: the accent trap ────────────────────────────────────────


@pytest.mark.parametrize(
    "verb,yo,el",
    [
        ("tener", "tuve", "tuvo"),
        ("estar", "estuve", "estuvo"),
        ("poder", "pude", "pudo"),
        ("poner", "puse", "puso"),
        ("saber", "supe", "supo"),
        ("querer", "quise", "quiso"),
        ("venir", "vine", "vino"),
    ],
)
def test_strong_preterites_carry_no_accent(verb: str, yo: str, el: str) -> None:
    """`tuve`, never *`tuvé`.

    Regular preterites ARE accented (`hablé`, `comí`), so the two ending sets are
    genuinely different and conflating them is the classic error.
    """
    f = forms(verb, "preterito")
    assert f["yo"] == yo
    assert f["el_ella_usted"] == el


def test_regular_preterites_by_contrast_are_accented() -> None:
    assert forms("hablar", "preterito")["yo"] == "hablé"
    assert forms("comer", "preterito")["el_ella_usted"] == "comió"


def test_hacer_shifts_c_to_z_before_o() -> None:
    """`hizo`, not *`hico` — the spelling change keeps the /θ/ sound."""
    f = forms("hacer", "preterito")
    assert f["yo"] == "hice"
    assert f["el_ella_usted"] == "hizo"


def test_j_stems_take_eron_not_ieron() -> None:
    """`dijeron`, never *`dijieron`."""
    assert forms("decir", "preterito")["ellos_ellas_ustedes"] == "dijeron"


def test_ser_and_ir_share_a_preterite() -> None:
    """A real syncretism in the language, not a copy-paste slip in the table."""
    assert forms("ser", "preterito") == forms("ir", "preterito")
    assert forms("ser", "preterito")["yo"] == "fui"


def test_dar_takes_er_endings_despite_being_ar() -> None:
    assert tuple(forms("dar", "preterito")[p] for p in PERSONS) == (
        "di",
        "diste",
        "dio",
        "dimos",
        "disteis",
        "dieron",
    )


# ── Orthographic changes: sound before spelling ───────────────────────────────


@pytest.mark.parametrize(
    "verb,expected",
    [("buscar", "busqué"), ("tocar", "toqué"), ("llegar", "llegué"), ("pagar", "pagué"), ("empezar", "empecé")],
)
def test_spelling_changes_preserve_the_stems_sound(verb: str, expected: str) -> None:
    """*`buscé` would be /busˈθe/. A learner writing it is marked wrong."""
    assert forms(verb, "preterito")["yo"] == expected


def test_the_same_change_applies_in_the_subjunctive() -> None:
    """Any e-initial ending triggers it, not just the preterite's."""
    assert forms("buscar", "subjuntivo_presente")["yo"] == "busque"
    assert forms("llegar", "subjuntivo_presente")["yo"] == "llegue"


# ── Stem changes: the boot ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verb,yo,nosotros",
    [
        ("pensar", "pienso", "pensamos"),
        ("poder", "puedo", "podemos"),
        ("pedir", "pido", "pedimos"),
        ("dormir", "duermo", "dormimos"),
        ("volver", "vuelvo", "volvemos"),
    ],
)
def test_stem_changes_skip_nosotros_and_vosotros(verb: str, yo: str, nosotros: str) -> None:
    """The "boot": four persons change, the two unstressed ones do not."""
    f = forms(verb)
    assert f["yo"] == yo
    assert f["nosotros"] == nosotros


def test_the_change_lands_on_the_stressed_syllable() -> None:
    """`empezar` → `empiezo`, not *`iempezo`.

    The rule replaces the LAST matching vowel, so a verb with two of them still
    changes the right one.
    """
    assert forms("empezar")["yo"] == "empiezo"


def test_stem_changes_do_not_leak_into_the_imperfect() -> None:
    """Only ser, ir and ver are irregular there; `poder` is not."""
    assert forms("poder", "imperfecto")["yo"] == "podía"


# ── Irregular presents ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verb,expected",
    [
        ("ser", ("soy", "eres", "es", "somos", "sois", "son")),
        ("estar", ("estoy", "estás", "está", "estamos", "estáis", "están")),
        ("ir", ("voy", "vas", "va", "vamos", "vais", "van")),
        ("tener", ("tengo", "tienes", "tiene", "tenemos", "tenéis", "tienen")),
        ("haber", ("he", "has", "ha", "hemos", "habéis", "han")),
        ("venir", ("vengo", "vienes", "viene", "venimos", "venís", "vienen")),
    ],
)
def test_high_frequency_irregular_presents(verb: str, expected: tuple[str, ...]) -> None:
    assert tuple(forms(verb)[p] for p in PERSONS) == expected


def test_tener_combines_an_irregular_yo_with_a_stem_change() -> None:
    """`tengo` but `tienes` — two separate irregularities in one verb."""
    f = forms("tener")
    assert f["yo"] == "tengo"
    assert f["tu"] == "tienes"
    assert f["nosotros"] == "tenemos"


# ── Subjunctive inherits from the yo-form ─────────────────────────────────────


@pytest.mark.parametrize(
    "verb,expected",
    [
        ("tener", "tenga"),
        ("hacer", "haga"),
        ("decir", "diga"),
        ("poner", "ponga"),
        ("venir", "venga"),
        ("salir", "salga"),
        ("ser", "sea"),
        ("ir", "vaya"),
        ("saber", "sepa"),
        ("haber", "haya"),
    ],
)
def test_the_subjunctive_is_built_from_the_yo_form(verb: str, expected: str) -> None:
    """`tengo` → `tenga`: the irregularity is inherited, not re-learned."""
    assert forms(verb, "subjuntivo_presente")["yo"] == expected


# ── Irregular future stems, shared with the conditional ──────────────────────


@pytest.mark.parametrize(
    "verb,fut,cond",
    [
        ("tener", "tendré", "tendría"),
        ("hacer", "haré", "haría"),
        ("decir", "diré", "diría"),
        ("salir", "saldré", "saldría"),
        ("querer", "querré", "querría"),
        ("haber", "habré", "habría"),
    ],
)
def test_one_irregular_stem_serves_both_future_and_conditional(
    verb: str, fut: str, cond: str
) -> None:
    assert forms(verb, "futuro")["yo"] == fut
    assert forms(verb, "condicional")["yo"] == cond


# ── Participles and gerunds ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verb,expected",
    [
        ("hablar", "hablado"),
        ("comer", "comido"),
        ("hacer", "hecho"),
        ("decir", "dicho"),
        ("ver", "visto"),
        ("escribir", "escrito"),
        ("abrir", "abierto"),
        ("volver", "vuelto"),
        ("poner", "puesto"),
    ],
)
def test_participles(verb: str, expected: str) -> None:
    assert participle(verb) == expected


@pytest.mark.parametrize("verb,expected", [("leer", "leído"), ("caer", "caído"), ("traer", "traído")])
def test_a_vowel_final_stem_takes_an_accented_participle(verb: str, expected: str) -> None:
    """*`leido` is a spelling error, not a variant.

    Without the accent the i forms a diphthong with the preceding vowel and the
    stress moves — a different word shape entirely.
    """
    assert participle(verb) == expected


@pytest.mark.parametrize(
    "verb,expected",
    [("hablar", "hablando"), ("comer", "comiendo"), ("ir", "yendo"), ("dormir", "durmiendo"), ("leer", "leyendo")],
)
def test_gerunds(verb: str, expected: str) -> None:
    assert gerund(verb) == expected


# ── Input validation ─────────────────────────────────────────────────────────


def test_ir_is_a_valid_two_letter_infinitive() -> None:
    """The one two-letter verb in the language; a stricter pattern would lose it."""
    assert conjugate("ir")["forms"]["yo"] == "voy"


@pytest.mark.parametrize("bad", ["", "  ", "hello", "hablo", "ar", "er", "sprechen"])
def test_non_infinitives_are_rejected(bad: str) -> None:
    """Rejected loudly rather than conjugated as if regular.

    `hablo` is a real word but not an infinitive; silently treating it as one
    would produce a paradigm of nonsense with no signal that anything is wrong.
    """
    with pytest.raises(ValueError):
        conjugate(bad)


def test_accented_and_enye_infinitives_are_accepted() -> None:
    assert conjugate("enseñar")["forms"]["yo"] == "enseño"
    assert conjugate("oír")["verb"] == "oír"


def test_the_engine_labels_itself_as_a_rule_engine() -> None:
    """`source` is what tells the tutor it may state this as fact."""
    c = conjugate("hablar")
    assert c["source"] == "rule_engine"
    assert c["is_irregular"] is False
    assert conjugate("ser")["is_irregular"] is True
