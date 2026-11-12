import pytest

from review_guidelines import EvidenceAnalysis


@pytest.fixture
def analysis_notes():
    return EvidenceAnalysis.model_validate({
        "papers": [{
            "paper_id": "P1", "method": {
                "text": "Graph analysis", "kind": "reported", "citations": [{"paper_id": "P1", "page": 1}],
            }, "data_and_metrics": None,
            "definitions": [], "findings": [{
                "text": "The supplied paper describes graph analysis.", "kind": "reported",
                "citations": [{"paper_id": "P1", "page": 1}],
            }], "limitations": [], "historical_role": None,
        }],
        "themes": [{
            "title": "Graph representations", "synthesis": [{
                "text": "Only one paper is supplied; cross-paper comparison is unavailable.", "kind": "inference",
                "citations": [{"paper_id": "P1", "page": 1}],
            }], "opposing_findings": [], "explanation_of_differences": "Insufficient comparative evidence.",
        }], "gaps": [],
    })
