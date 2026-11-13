import json
from unittest.mock import MagicMock

import pymupdf
import pytest

import pdf_reading as pdf
from ai_backend import AIBackendError, AISettings
from storage import HistoryStore

SETTINGS = AISettings('openai_api', 'openai/example', 'test')


def document(count=7, text=True):
    with pymupdf.open() as doc:
        for i in range(count):
            page = doc.new_page()
            if text:
                page.insert_text((72, 72), f'Page {i + 1}: Finding in this section.')
            page.draw_rect(pymupdf.Rect(70, 100, 160, 180), color=(1, 0, 0), fill=(0, 0, 1))
        return doc.tobytes()


def mock_download(monkeypatch, data):
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [data]
    monkeypatch.setattr(pdf.requests, 'get', lambda *a, **kw: response)


def fake_reader(prompt, schema, settings, *, images=None):
    entries = json.loads(prompt.split('Input entries JSON: ')[1])
    assert len(images) == len(entries)
    assert all(image.startswith(b'\x89PNG') for image in images)
    return pdf.BatchReading(pages=[pdf.PageReading(
        page=entry['page'], part=entry['part'], status='readable', limitations='',
        observations=[pdf.Observation(text=f"A figure on page {entry['page']}.", kind='reported', content_type='figure')],
    ) for entry in entries])


def test_every_page_including_middle_and_end_is_read_with_images(monkeypatch):
    calls = []
    def reader(prompt, schema, settings, **kwargs):
        result = fake_reader(prompt, schema, settings, **kwargs)
        calls.append([page.page for page in result.pages])
        return result
    monkeypatch.setattr(pdf, 'read_structured', reader)
    monkeypatch.setenv('PDF_BATCH_PAGES', '3')
    progress = []
    result = pdf.read_pdf(document(8), 'P1', 'graphs', SETTINGS, progress.append)
    assert calls == [[1, 2, 3], [4, 5, 6], [7, 8]]
    assert result['processed_pages'] == result['page_count'] == 8
    assert result['citation_pages'] == list(range(1, 9))
    assert result['coverage'] == 'multimodal PDF' and result['batch_count'] == 3
    assert [p['page'] for p in result['pages']] == list(range(1, 9))
    assert '8/8' in progress[-1]
    assert 'image_url' not in json.dumps(result) and 'base64' not in json.dumps(result)


def test_scan_is_sent_as_image_even_without_extracted_text(monkeypatch):
    def reader(prompt, schema, settings, **kwargs):
        entries = json.loads(prompt.split('Input entries JSON: ')[1])
        assert entries[0]['text'] == ''
        return fake_reader(prompt, schema, settings, **kwargs)
    monkeypatch.setattr(pdf, 'read_structured', reader)
    result = pdf.read_pdf(document(1, text=False), 'P1', 'graphs', SETTINGS, lambda _: None)
    assert result['coverage'] == 'multimodal PDF'
    assert result['pages'][0]['observations'][0]['content_type'] == 'figure'


def test_page_text_parts_have_no_silent_omission(monkeypatch):
    monkeypatch.setattr(pdf, 'PAGE_TEXT_PART', 10)
    monkeypatch.setattr(pdf, 'MAX_BATCH_TEXT', 20)
    with pymupdf.open(stream=document(1), filetype='pdf') as doc:
        original = doc[0].get_text().strip()
        batches = list(pdf.page_batches(doc, 4))
    entries = [entry for batch in batches for entry in batch]
    assert ''.join(entry.text for entry in entries) == original
    assert [entry.part for entry in entries] == list(range(1, len(entries) + 1))
    assert all(entry.page == 1 and entry.parts == len(entries) for entry in entries)
    assert all(sum(len(entry.text) for entry in batch) <= 20 for batch in batches)
    image = pymupdf.Pixmap(entries[0].image)
    assert max(image.width, image.height) <= pdf.IMAGE_EDGE + 1


def test_image_payload_budget_can_split_batches_without_losing_pages(monkeypatch):
    monkeypatch.setattr(pdf, 'MAX_BATCH_IMAGES_BYTES', 10)
    monkeypatch.setattr(pdf, 'render_page', lambda page: b'123456')
    with pymupdf.open(stream=document(3), filetype='pdf') as doc:
        batches = list(pdf.page_batches(doc, 4))
    assert [[entry.page for entry in batch] for batch in batches] == [[1], [2], [3]]


def test_large_page_image_is_resized_until_it_fits(monkeypatch):
    monkeypatch.setattr(pdf, 'MAX_IMAGE_BYTES', 10)
    scales = []
    class Page:
        rect = pymupdf.Rect(0, 0, 1000, 1000)
        def get_pixmap(self, **kwargs):
            scales.append(kwargs['matrix'].a)
            pixmap = MagicMock()
            pixmap.tobytes.return_value = b'large-image' if len(scales) == 1 else b'small'
            return pixmap
    assert pdf.render_page(Page()) == b'small'
    assert scales[1] < scales[0]


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'foreign', 'wrong_part'])
def test_batch_must_account_for_exact_pages_and_parts(monkeypatch, mode):
    def reader(*args, **kwargs):
        result = fake_reader(*args, **kwargs)
        if mode == 'missing':
            result.pages.pop()
        elif mode == 'duplicate':
            result.pages[1] = result.pages[0]
        elif mode == 'foreign':
            result.pages[0].page = 99
        else:
            result.pages[0].part = 99
        return result
    monkeypatch.setattr(pdf, 'read_structured', reader)
    with pytest.raises(AIBackendError, match='every supplied page'):
        pdf.read_pdf(document(2), 'P1', 'graphs', SETTINGS, lambda _: None)


def test_unreadable_pages_remain_visible_but_cannot_supply_claims(monkeypatch):
    def reader(*args, **kwargs):
        result = fake_reader(*args, **kwargs)
        result.pages[0] = pdf.PageReading(page=1, part=1, status='unreadable', observations=[], limitations='Small labels illegible.')
        return result
    monkeypatch.setattr(pdf, 'read_structured', reader)
    result = pdf.read_pdf(document(2), 'P1', 'graphs', SETTINGS, lambda _: None)
    assert result['coverage'] == 'limited multimodal PDF'
    assert result['limited_pages'] == [1] and result['citation_pages'] == [2]
    assert result['processed_pages'] == 2


def test_second_batch_failure_stops_instead_of_claiming_full_coverage(monkeypatch):
    calls = []
    def reader(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise AIBackendError('Vision unavailable')
        return fake_reader(*args, **kwargs)
    monkeypatch.setattr(pdf, 'read_structured', reader)
    with pytest.raises(AIBackendError, match='Vision unavailable'):
        pdf.read_pdf(document(5), 'P1', 'graphs', SETTINGS, lambda _: None)


def test_page_limit_fails_before_any_model_call(monkeypatch):
    monkeypatch.setenv('PDF_MAX_PAGES', '1')
    monkeypatch.setattr(pdf, 'read_structured', lambda *a, **kw: pytest.fail('Must not call AI'))
    with pytest.raises(AIBackendError, match='PDF_MAX_PAGES=1'):
        pdf.read_pdf(document(2), 'P1', 'graphs', SETTINGS, lambda _: None)


def test_pdf_cache_and_download_limit(monkeypatch, tmp_path):
    store = HistoryStore(tmp_path / 'history.sqlite3')
    data = document(1)
    mock_download(monkeypatch, data)
    url = 'https://arxiv.org/pdf/example'
    assert pdf.load_pdf(url, store) == data
    monkeypatch.setattr(pdf.requests, 'get', lambda *a, **kw: pytest.fail('Cache must avoid network'))
    assert pdf.load_pdf(url, store) == data
    monkeypatch.setattr(pdf, 'MAX_PDF_BYTES', 4)
    with pytest.raises(ValueError, match='download limit'):
        pdf.load_pdf(url, store)
    mock_download(monkeypatch, b'12345')
    with pytest.raises(ValueError, match='download limit'):
        pdf.load_pdf('https://arxiv.org/pdf/other')


def test_hierarchical_reduction_bounds_context_and_preserves_page_citations(monkeypatch):
    notes = [{'text': 'Evidence ' * 75, 'kind': 'reported', 'citations': [{'paper_id': 'P1', 'page': i}]} for i in range(1, 101)]
    calls = []
    def reader(prompt, schema, settings):
        data = json.loads(prompt.split('Evidence JSON:\n')[1])
        calls.append(data)
        pairs = sorted(pdf.citation_pairs(data))
        return pdf.EvidenceDigest(notes=[{'text': 'Combined findings.', 'kind': 'reported',
                                         'citations': [{'paper_id': pid, 'page': page} for pid, page in pairs]}])
    monkeypatch.setattr(pdf, 'read_structured', reader)
    result, levels = pdf.reduce_notes(notes, 'graphs', SETTINGS, lambda _: None)
    assert calls and levels >= 1
    assert len(json.dumps(result, separators=(',', ':'))) <= pdf.PAPER_CONTEXT
    assert pdf.citation_pairs(result) == {('P1', i) for i in range(1, 101)}


def test_reduction_rejects_invented_page(monkeypatch):
    notes = [{'text': 'Evidence ' * 75, 'kind': 'reported', 'citations': [{'paper_id': 'P1', 'page': 1}]}] * 40
    monkeypatch.setattr(pdf, 'read_structured', lambda *a: pdf.EvidenceDigest(notes=[{
        'text': 'Invented', 'kind': 'reported', 'citations': [{'paper_id': 'P1', 'page': 99}],
    }]))
    with pytest.raises(AIBackendError, match='unsupplied citation'):
        pdf.reduce_notes(notes, 'graphs', SETTINGS, lambda _: None)
