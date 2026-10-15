"""Named-page decisions follow independent labels and preserve the existing text oracle."""
import copy
import sys
import pytest
from conftest import load_tool_verify

@pytest.mark.parametrize('labels', [[1], [1, 2], []])
def test_named_pdf_attribution_requires_the_measured_label_state(monkeypatch, labels):
    f = load_tool_verify()
    monkeypatch.setitem(sys.modules,'tool_verify',f)
    cloud = sys.modules['verify_acts_cloud']
    monkeypatch.setattr(cloud,'_drawing_original_sheet',lambda: {'name':'Original'})
    monkeypatch.setattr(cloud,'_pdf_layer_strings',lambda *_: (labels,'text',1,2))
    seen = []
    def strict_text(path):
        seen.append(path)
        return lambda p: p['sheets'][0]['pdf_page'] == 1 and p['sheets'][0]['text'] == ['dimension80']
    monkeypatch.setattr(cloud,'_drawing_text_read',strict_text)
    payload = {'sheet_count':2,'pdf':{'file':'fixture.pdf','page_count':2},
               'sheets':[{'name':'Original','pdf_page':None,'text':None,
                          'pdf_page_reason':"2 pages are labelled with this sheet's name"}]}
    check = cloud._drawing_named_text_read('fixture.pdf')
    if labels == [1]:
        payload['sheets'][0].update(pdf_page=1,text=['dimension80'])
        assert check(payload) and seen == ['fixture.pdf']
        payload['sheets'][0]['pdf_page'] = 2
        assert not check(payload)
    elif labels == [1, 2]:
        assert check(payload) and not seen
        wrong = copy.deepcopy(payload);wrong['sheets'][0].update(pdf_page=1,text=['invented'])
        with pytest.raises(AssertionError): check(wrong)
        wrong = copy.deepcopy(payload);wrong['pdf']['file'] = 'other.pdf'
        with pytest.raises(AssertionError): check(wrong)
    else:
        with pytest.raises(AssertionError): check(payload)
