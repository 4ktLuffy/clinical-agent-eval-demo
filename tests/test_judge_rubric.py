from eval.judge import JudgeScore, RuleJudge

CONTEXT = (
    "Visiting hours on the general wards are 11am to 8pm every day. "
    "Two visitors are allowed at the bedside at any one time."
)
CHUNKS = {"clinical-faq.md#0": CONTEXT}


def test_faithful_answer_scores_above_an_unsupported_one():
    judge = RuleJudge()
    faithful = judge.score(
        "Visiting hours on the general wards are 11am to 8pm every day.",
        CONTEXT,
        ["clinical-faq.md#0"],
        CHUNKS,
    )
    invented = judge.score(
        "Visiting is restricted to relatives holding a permit issued by the parking office.",
        CONTEXT,
        ["clinical-faq.md#0"],
        CHUNKS,
    )
    assert faithful.faithfulness > invented.faithfulness
    assert faithful.faithful and not invented.faithful


def test_score_shape():
    score = RuleJudge().score("Visiting hours are 11am to 8pm.", CONTEXT, [], CHUNKS)
    assert isinstance(score, JudgeScore)
    assert isinstance(score.faithful, bool)
    assert 0.0 <= score.faithfulness <= 1.0
    assert 0.0 <= score.citation_quality <= 1.0


def test_uncited_answer_gets_no_citation_credit():
    assert RuleJudge().score("Visiting hours are 11am to 8pm.", CONTEXT, [], CHUNKS).citation_quality == 0.0
