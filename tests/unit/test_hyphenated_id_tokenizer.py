"""Root-cause unit test for the hyphen-numeric ID tokenizer asymmetry.

Known limitation tracked as issues #951/#952. pg-raggraph v0.9.0 (bento
commit 00346a7d integration) rewrote retrieval onto native BM25+pgvector RRF
(issue #96) but did not fix ``_to_or_tsquery``'s naive tokenizer.

A hyphen-numeric ID like ``INC-0001`` is stored in ``chunks.search_vector``
as two lexemes -- ``'inc'`` and ``'-0001'`` -- because Postgres's own text
search parser treats a leading-hyphen digit run as a distinct "signed
integer" token from the preceding word (verified: ``ts_debug('english',
'INC-0001')`` emits an ``asciiword`` token 'INC' -> lexeme 'inc' and an
``int`` token '-0001' -> lexeme '-0001', unchanged). ``_to_or_tsquery``
pre-splits the question with a bare ``re.findall(r"\\w+", ...)`` *before*
handing anything to ``to_tsquery`` -- the hyphen is gone by the time
Postgres ever sees it, so the query becomes ``'inc' | '0001'`` and
``'0001'`` can never match the stored ``'-0001'`` lexeme.

See tests/integration/test_hyphenated_id_tokenizer_it.py for the retrieval-
ranking consequence (a decoy chunk that merely repeats "Inc" can out-rank
the actual ID chunk under the default ts_rank backend).
"""

from __future__ import annotations

from pg_raggraph.retrieval import _to_or_tsquery


def test_to_or_tsquery_drops_hyphen_from_hyphen_numeric_id():
    """Root cause: '\\w+' splits 'INC-0001' into 'inc' + '0001' -- never the
    '-0001' lexeme Postgres's own parser stores for the same text."""
    tsquery = _to_or_tsquery("what is the status of INC-0001?")
    terms = tsquery.split(" | ")
    assert "inc" in terms
    assert "0001" in terms
    assert "-0001" not in terms
    assert not any(term.startswith("-") for term in terms)


def test_to_or_tsquery_drops_hyphen_from_multiple_ids():
    """Same defect across several IDs in one question -- every hyphen is
    lost, not just the first."""
    tsquery = _to_or_tsquery("compare INC-0001 against INC-0042")
    terms = tsquery.split(" | ")
    assert "0001" in terms
    assert "0042" in terms
    assert not any(term.startswith("-") for term in terms)
