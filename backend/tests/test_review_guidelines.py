import pytest
from pydantic import ValidationError

from review_guidelines import ReviewOptions, check_review, ensure_study_placeholders, validate_analysis, writing_prompt


def test_analysis_cannot_cite_unknown_papers_or_unseen_pages(analysis_notes):
    evidence = [{"id": "P1", "text": "[Page 1] Method", "coverage": "sampled PDF"}]
    validate_analysis(analysis_notes, evidence)
    citation = analysis_notes.themes[0].synthesis[0].citations[0]
    citation.page = 3
    with pytest.raises(ValueError, match="outside"):
        validate_analysis(analysis_notes, evidence)
    citation.page = 1
    citation.paper_id = "P2"
    with pytest.raises(ValueError, match="outside"):
        validate_analysis(analysis_notes, evidence)


def test_analysis_requires_each_selected_paper_exactly_once(analysis_notes):
    evidence = [{"id": "P1", "text": "[Page 1] Evidence"}]
    analysis_notes.papers.append(analysis_notes.papers[0].model_copy(deep=True))
    with pytest.raises(ValueError, match="exactly once"):
        validate_analysis(analysis_notes, evidence)


def test_abstract_evidence_cannot_claim_pdf_pages(analysis_notes):
    evidence = [{"id": "P1", "text": "Abstract only", "coverage": "abstract only"}]
    with pytest.raises(ValueError, match="outside"):
        validate_analysis(analysis_notes, evidence)
    analysis_notes.papers[0].findings[0].citations[0].page = None
    analysis_notes.papers[0].method.citations[0].page = None
    analysis_notes.themes[0].synthesis[0].citations[0].page = None
    validate_analysis(analysis_notes, evidence)


def test_pdf_analysis_must_name_the_supplied_page(analysis_notes):
    analysis_notes.papers[0].findings[0].citations[0].page = None
    with pytest.raises(ValueError, match="must cite"):
        validate_analysis(analysis_notes, [{"id": "P1", "text": "[Page 1] Evidence"}])


def test_citation_checks_do_not_count_appended_references_as_body_citations():
    evidence = [{"id": "P1", "text": "[Page 1] Evidence", "coverage": "full PDF"}]
    checks = check_review("Uncited claims.\n\n## Sources and coverage\n\n- [P1] Title", evidence)
    assert checks[0]["status"] == checks[1]["status"] == "warning"
    assert "No supplied sources" in checks[0]["details"]


def test_citation_checks_flag_unknown_sources_and_unsupplied_pages():
    evidence = [{"id": "P1", "text": "[Page 2] Evidence", "coverage": "sampled PDF"}]
    checks = check_review("A [P1, p. 3] and B [P9].", evidence)
    assert "Unknown source P9" in checks[0]["details"]
    assert "Page 3" in checks[0]["details"]
    assert checks[2]["status"] == "warning"
    good = check_review("A [P1, p. 2].", evidence)
    assert good[0]["status"] == good[1]["status"] == "pass"


def test_citation_checks_reject_unchecked_page_range_syntax():
    checks = check_review("A [P1, pp. 1-99].", [{"id": "P1", "text": "[Page 1] Text", "coverage": "full PDF"}])
    assert checks[0]["status"] == "warning"
    assert "Unsupported citation format" in checks[0]["details"]


def test_introduction_options_preserve_user_context_and_reject_extra_configuration():
    options = ReviewOptions(mode="introduction", research_question="  Can this transfer?  ", units="layouts")
    assert options.research_question == "Can this transfer?"
    prompt = writing_prompt("layout analysis", options)
    assert "Can this transfer?" in prompt and "layouts" in prompt
    assert "EVERY missing study detail" in prompt and "待補" in prompt
    with pytest.raises(ValidationError):
        ReviewOptions(model="browser-model")
    with pytest.raises(ValidationError):
        ReviewOptions(context="x" * 3001)


def test_missing_study_details_are_present_even_if_writer_omits_placeholders():
    options = ReviewOptions(mode="introduction", research_question="Does this transfer?", units="layouts")
    draft = ensure_study_placeholders("# Draft\n[待補：研究情境]", options)
    assert "[待補：研究目標]" in draft and "[待補：預期貢獻]" in draft
    assert "[待補：研究問題]" not in draft and "[待補：分析單位]" not in draft
    assert draft.count("[待補：研究情境]") == 1
    assert ensure_study_placeholders("# Review", ReviewOptions()) == "# Review"


def test_complex_multi_source_page_syntax_cannot_bypass_page_checks():
    checks = check_review("[P1, p. 1; P2, p. 999]", [
        {"id": "P1", "coverage": "full PDF", "text": "[Page 1] Text"},
        {"id": "P2", "coverage": "full PDF", "text": "[Page 1] Text"},
    ])
    assert checks[0]["status"] == "warning"
    assert "Unsupported citation format" in checks[0]["details"]
