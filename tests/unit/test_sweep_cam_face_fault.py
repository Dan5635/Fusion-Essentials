"""Reject a fault or restore witness that belongs to another operation or height state."""
import copy
import sys
import pytest
from conftest import load_tool_verify

@pytest.mark.parametrize('wrong', ['id', 'tool', 'top', 'offset', 'fault', 'suppression', 'unread_error'])
def test_face_fault_witness_rejects_wrong_target_or_state(monkeypatch, wrong):
    f = load_tool_verify()
    monkeypatch.setitem(sys.modules,'tool_verify',f)
    cam = sys.modules['verify_acts_cam']
    zero = {'expression':'0mm','value':0.0,'error':'','enabled':True,'editable':True}
    before = {'operation':'FaceDiscriminatorOp','id':3,'has_error':False,'suppressed':False,
              'tool_sha256':'6f23f4a38aa2ba33b9dbf44dbc8432b9444bebb38daf2f3b13331919b6439717',
              'parameters':{'topHeight_offset':copy.deepcopy(zero),'bottomHeight_offset':copy.deepcopy(zero)}}
    monkeypatch.setitem(cam._RECALL,'face_op',before['operation'])
    monkeypatch.setitem(cam._RECALL,'face_fault_before',before)
    assert cam._face_fault_restored(copy.deepcopy(before))
    seeded = copy.deepcopy(before)
    seeded['has_error'] = True
    seeded['parameters']['bottomHeight_offset'].update(expression='50 mm',value=5.0)
    assert cam._face_fault_seeded(seeded)
    seeded['parameters']['topHeight_offset']['error'] = 'The top height must not be below the bottom height.'
    assert cam._face_fault_seeded(seeded)
    assert not cam._partial_snapshot_known(seeded,before['operation'],list(before['parameters']))
    if wrong == 'id': seeded['id'] = 4
    elif wrong == 'tool': seeded['tool_sha256'] = 'a'*64
    elif wrong == 'top': seeded['parameters']['topHeight_offset']['value'] = 0.1
    elif wrong == 'offset': seeded['parameters']['bottomHeight_offset']['value'] = 0.0
    elif wrong == 'fault': seeded['has_error'] = False
    elif wrong == 'suppression': seeded['suppressed'] = True
    else: seeded['parameters']['topHeight_offset']['error'] = None
    with pytest.raises(AssertionError):
        cam._face_fault_seeded(seeded)
    with pytest.raises(AssertionError):
        cam._face_fault_restored(seeded)
