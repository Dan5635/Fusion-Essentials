# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

import ast
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'live'))
import measure_api as m

ERROR = "RuntimeError: 3 : Camera type must be orthographic for extents"
BOUND = dict(row_id="camera-supported-perspective-extents-outcome",nonce="fresh",scratch="session:owned",source_sha256="abc",member="getExtents",camera_type=1)

@pytest.mark.parametrize('change,bad,payload',[
    (None,True,ERROR),
    ({'nonce':'old'},True,ERROR),
    ({'member':'setExtents'},True,ERROR),
    ({'object_type':'adsk::core::Viewport'},True,ERROR),
    ({'camera_type':None,'expected_type':None},True,ERROR),
    ({'camera_type':0,'expected_type':0},True,ERROR),
    ({'camera_type':2,'expected_type':2},True,ERROR),
    ({'phase':'returned'},True,ERROR),
    ({},True,'RuntimeError: unrelated preparation failure'),
    ({},False,ERROR),
])
def test_unattributed_or_returned_camera_error_cannot_pass(change,bad,payload):
    marker = dict(BOUND,phase='ready',camera_type=1,expected_type=1,object_type='adsk::core::Camera')
    assert m._judge_camera_extents(marker,True,ERROR,BOUND)[0]=='PASS'
    if change is None:
        marker = None
    else:
        marker.update(change)
    assert m._judge_camera_extents(marker,bad,payload,BOUND)[0] in ('ERROR','FAIL')

def test_getter_and_setter_need_two_fresh_bound_native_results(monkeypatch,tmp_path):
    seen = []
    def call(name,args):
        assert name=='sys_execute_script' and args['expect_document']=='session:owned'
        constants = {}
        for node in ast.walk(ast.parse(args['script'])):
            if (isinstance(node,ast.Assign) and len(node.targets)==1
                    and isinstance(node.targets[0],ast.Name) and isinstance(node.value,ast.Constant)):
                constants[node.targets[0].id]=node.value.value
        seen.append(constants)
        marker = dict(row_id=BOUND['row_id'],nonce=constants['nonce'],scratch=constants['scratch'],
                      source_sha256=constants['source_sha'],member=constants['member'],phase='ready',
                      camera_type=1,expected_type=1,object_type='adsk::core::Camera')
        Path(constants['path']).write_text(json.dumps(marker))
        return True,ERROR
    monkeypatch.setattr(m,'REPO_ROOT',str(tmp_path))
    monkeypatch.setattr(m,'call',call)
    row = next(r for r in m.ROWS if r['id']==BOUND['row_id'])
    assert m._measure_camera_extents(row,'session:owned')[0]=='PASS'
    assert [c['member'] for c in seen]==['getExtents','setExtents']
    assert seen[0]['nonce']!=seen[1]['nonce'] and seen[0]['path']!=seen[1]['path']
