"""content language on documents, vocabulary and feed sources

Revision ID: b1c4a7e90f11
Revises: 8a76afe82eee
Create Date: 2026-08-03

`users.target_language` already existed, and its comment claimed a second target
language would be "a content problem, not a schema migration". That was half
true. The learner's choice was stored, but the CONTENT carried no language at
all: `documents`, `vocabulary` and `feed_sources` were implicitly German. A
learner who switched to Spanish would have been served German readers, German
flashcards and German quiz material — silently, with no error to notice.

So the language of a piece of content has to be data, exactly like the language
of a learner. Then "show me my library" becomes a filter rather than an
assumption.

Backfilled to 'de' because every row that exists today IS German — the platform
has only ever taught German. That is a statement about history, not a default
that happens to be convenient.

NOT NULL with a server default: content without a language is unservable (we
would not know which learner it belongs to), so the database refuses it rather
than letting a NULL propagate into a query that silently matches nobody.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# `chunks.embedding` is a pgvector column; autogenerate references
# `pgvector.sqlalchemy...` without importing it, so it is imported here for
# every migration rather than being re-fixed by hand each time.
import pgvector.sqlalchemy  # noqa: F401

revision: str = "b1c4a7e90f11"
down_revision: Union[str, Sequence[str], None] = "8a76afe82eee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ISO 639-1. Two chars is enough for the target languages we teach; regional
# variants (de-AT, pt-BR) are a presentation concern, not a content one.
_LANG = sa.String(length=5)


def upgrade() -> None:
    for table in ("documents", "vocabulary", "feed_sources"):
        op.add_column(
            table,
            sa.Column(
                "language",
                _LANG,
                nullable=False,
                server_default="de",
                comment="Target language this content teaches (ISO 639-1).",
            ),
        )
        # Every read is "this learner's language, then narrow further", so the
        # language column leads the index. Without it, adding a second language
        # turns every library and vocabulary query into a full scan that
        # discards most of what it reads.
        op.create_index(f"ix_{table}_language", table, ["language"])

    # The library's hot query is (language, status, created_at desc) for the feed
    # and (language, cefr_level) for level filtering. One composite each beats
    # three single-column indexes the planner has to combine.
    op.create_index(
        "ix_documents_language_status_created",
        "documents",
        ["language", "status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_vocabulary_user_language",
        "vocabulary",
        ["user_id", "language"],
    )

    # LANGUAGE joins the uniqueness key. A learner studying German and Spanish
    # must be able to save both "sin" (German, without) and "sin" (Spanish); the
    # old (user_id, lemma) key made the second one look like a duplicate, and
    # vocab.py's IntegrityError handler would have returned the German row as
    # though the Spanish save had succeeded.
    op.drop_constraint("uq_vocab_user_lemma", "vocabulary", type_="unique")
    op.create_unique_constraint(
        "uq_vocab_user_lang_lemma", "vocabulary", ["user_id", "language", "lemma"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_vocab_user_lang_lemma", "vocabulary", type_="unique")
    op.create_unique_constraint("uq_vocab_user_lemma", "vocabulary", ["user_id", "lemma"])
    op.drop_index("ix_vocabulary_user_language", table_name="vocabulary")
    op.drop_index("ix_documents_language_status_created", table_name="documents")
    for table in ("documents", "vocabulary", "feed_sources"):
        op.drop_index(f"ix_{table}_language", table_name=table)
        op.drop_column(table, "language")
