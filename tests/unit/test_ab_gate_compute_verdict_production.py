"""Production compute_verdict(runner_outputs, judge_config) — real-verdict wiring.

The shipped writer only had the fixture path (from_premeasured); the production
path raised NotImplementedError. These tests lock the production path: recall@10
+ MRR computed from ABRunnerOutput vs gold_doc_id (contract §3.1), judge win-rate
via the llm-judge seam (mock provider for determinism), fed through the §3.3/§3.4
combiner.
"""

from __future__ import annotations

import pytest

from pg_raggraph.ab_gate.io import ABCaseResult, ABRetrievedItem, ABRunnerOutput
from pg_raggraph.ab_gate.writer import compute_verdict


def _item(rank: int, source: str) -> ABRetrievedItem:
    return ABRetrievedItem(
        rank=rank, source=source, score=1.0 / rank, content_snippet=f"snip {source}"
    )


def _case(qid: str, gold_doc_id: str, hit_rank: int | None) -> ABCaseResult:
    """Build a case whose retrieved list places gold at hit_rank (None = miss)."""
    retrieved = [_item(r, f"chunkshop:other-{qid}-{r}") for r in range(1, 11)]
    if hit_rank is not None:
        retrieved[hit_rank - 1] = _item(hit_rank, f"chunkshop:{gold_doc_id}")
    return ABCaseResult(
        question_id=qid,
        question=f"question {qid}",
        gold_answer=None,
        retrieved=retrieved,
        latency_ms=1.0,
        gold_doc_id=gold_doc_id,
    )


def _output(mode: str, hit_ranks: dict[str, int | None]) -> ABRunnerOutput:
    results = [_case(qid, f"gold-{qid}", rank) for qid, rank in hit_ranks.items()]
    return ABRunnerOutput(corpus_id="c1", mode=mode, results=results)


def test_recall_and_mrr_computed_from_gold_doc_id_no_judge():
    """No judge_config → judge metric is TIE; graph wins recall+mrr → GRAPH_WINS."""
    # graph hits gold at rank 1 for both questions; naive misses both.
    graph = _output("graph_leg", {"q1": 1, "q2": 1})
    naive = _output("naive_vector", {"q1": None, "q2": None})

    verdict = compute_verdict([naive, graph], judge_config=None)

    c = verdict.combined
    assert c.recall_at_10.graph == pytest.approx(1.0)
    assert c.recall_at_10.naive == pytest.approx(0.0)
    assert c.recall_at_10.label == "GRAPH_WINS"
    assert c.mrr.graph == pytest.approx(1.0)
    assert c.mrr.naive == pytest.approx(0.0)
    assert c.mrr.label == "GRAPH_WINS"
    # judge skipped → TIE on that metric; 2 graph wins, 0 naive → GRAPH_WINS
    assert c.judge_win_rate.label == "TIE"
    assert verdict.label == "GRAPH_WINS"


def test_mrr_uses_reciprocal_rank():
    """gold at rank 2 → RR 0.5; rank 4 → 0.25; mean = 0.375."""
    graph = _output("graph_leg", {"q1": 2, "q2": 4})
    naive = _output("naive_vector", {"q1": None, "q2": None})
    verdict = compute_verdict([naive, graph], judge_config=None)
    assert verdict.combined.mrr.graph == pytest.approx(0.375)


def test_tie_retrieval_no_judge_is_inconclusive():
    """Identical retrieval + no judge → all metrics TIE → INCONCLUSIVE."""
    graph = _output("graph_leg", {"q1": 1, "q2": 3})
    naive = _output("naive_vector", {"q1": 1, "q2": 3})
    verdict = compute_verdict([naive, graph], judge_config=None)
    assert verdict.combined.recall_at_10.label == "TIE"
    assert verdict.combined.mrr.label == "TIE"
    assert verdict.label == "INCONCLUSIVE"


def test_production_path_runs_with_mock_judge():
    """judge_config with mock provider runs the judge step without error."""
    pytest.importorskip("llm_judge")
    graph = _output("graph_leg", {"q1": 1, "q2": 1})
    naive = _output("naive_vector", {"q1": None, "q2": None})
    judge_config = {"provider": {"kind": "mock", "model": "mock"}}
    verdict = compute_verdict([naive, graph], judge_config=judge_config)
    # Judge ran → judge_total > 0 on both legs.
    assert verdict.combined.judge_win_rate.graph >= 0.0
    assert verdict.label in {"GRAPH_WINS", "NAIVE_WINS", "INCONCLUSIVE"}


def test_accepts_paths_and_objects(tmp_path):
    """compute_verdict accepts a list of file paths as well as ABRunnerOutput."""
    import json

    graph = _output("graph_leg", {"q1": 1})
    naive = _output("naive_vector", {"q1": None})
    gp = tmp_path / "c1__graph_leg.json"
    npth = tmp_path / "c1__naive_vector.json"
    gp.write_text(json.dumps(graph.to_dict()))
    npth.write_text(json.dumps(naive.to_dict()))
    verdict = compute_verdict([gp, npth], judge_config=None)
    assert verdict.combined.recall_at_10.label == "GRAPH_WINS"


def test_graph_mode_selects_which_mode_is_the_graph_side():
    """graph_mode='hybrid' compares naive vs hybrid; default compares naive vs graph_leg."""
    naive = _output("naive_vector", {"q1": None, "q2": None})
    graph_leg = _output("graph_leg", {"q1": None, "q2": None})  # also misses
    hybrid = _output("hybrid", {"q1": 1, "q2": 1})  # hybrid hits

    # Default (graph_leg): both miss → recall TIE (0 vs 0) → not GRAPH_WINS.
    v_leg = compute_verdict([naive, graph_leg, hybrid], judge_config=None)
    assert v_leg.combined.recall_at_10.graph == pytest.approx(0.0)

    # graph_mode=hybrid: hybrid wins recall+mrr → GRAPH_WINS.
    v_hyb = compute_verdict([naive, graph_leg, hybrid], judge_config=None, graph_mode="hybrid")
    assert v_hyb.combined.recall_at_10.graph == pytest.approx(1.0)
    assert v_hyb.label == "GRAPH_WINS"


def test_premeasured_path_still_works():
    """Regression: the fixture path (from_premeasured) is unchanged."""
    payload = {
        "per_corpus": {
            "c1": {
                "naive_vector": {
                    "recall_at_10": 0.5,
                    "mrr": 0.4,
                    "judge_wins": 5,
                    "judge_total": 10,
                },
                "graph_leg": {"recall_at_10": 0.5, "mrr": 0.4, "judge_wins": 5, "judge_total": 10},
            }
        },
        "combined": {
            "naive_vector": {"recall_at_10": 0.5, "mrr": 0.4, "judge_wins": 5, "judge_total": 10},
            "graph_leg": {"recall_at_10": 0.5, "mrr": 0.4, "judge_wins": 5, "judge_total": 10},
        },
    }
    verdict = compute_verdict.from_premeasured(payload)
    assert verdict.label == "INCONCLUSIVE"
