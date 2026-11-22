import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.routers import ai
from app.store import Store


def test_explicit_demo_uses_only_presets_and_calls_model(monkeypatch, tmp_path):
    monkeypatch.setenv('ADVISORY_SHOW_DEMO', '1')
    monkeypatch.setenv('ADVISORY_DEMO_CALL_MODEL', '1')
    monkeypatch.setenv('ADVISORY_AUDIT_FILE', str(tmp_path / 'audit.jsonl'))
    monkeypatch.setenv('ADVISORY_SNAPSHOT_FILE', str(tmp_path / 'snapshots.jsonl'))
    monkeypatch.setattr(ai, '_config', lambda: ('key', 'model'))
    monkeypatch.setattr(ai, 'rank_candidates', lambda *args: [])
    calls = []
    def fake_model(key, model, message, context):
        calls.append((message, context))
        return '这是演示分析。', {}
    monkeypatch.setattr(ai, '_call_model', fake_model)
    store = Store(Settings.from_env())
    def forbidden_source():
        raise AssertionError('Demo must not read operational sources')
    store.advisory_snapshot_provider = forbidden_source
    store.snapshot = forbidden_source
    app = FastAPI()
    app.state.store = store
    app.include_router(ai.router, prefix='/api')
    result = TestClient(app).post('/api/ai/advice', json={
        'message': '请分析演示任务', 'scenario': 'demo', 'program_type': 'departure'}).json()
    assert len(calls) == 1
    assert calls[0][0] == '请分析演示任务'
    assert calls[0][1]['demo_only'] is True
    assert calls[0][1]['airport']['code'] == 'LAC-DEMO'
    assert calls[0][1]['data_freshness'] == 'unknown'
    assert result['conclusion'] == 'INSUFFICIENT_DATA'
    assert result['context']['demo_only'] is True
    assert result['context']['engine_verdict']['recommended'] is None
    assert result['executed'] is False
    assert result['advice'] == '这是演示分析。'


def test_model_receives_demo_instructions_only_for_demo_context(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        return io.BytesIO(json.dumps({
            'choices': [{'message': {'content': '模拟分析'}, 'finish_reason': 'stop'}]
        }).encode())

    monkeypatch.setattr(ai, 'urlopen', fake_urlopen)
    ai._call_model('key', 'model', '分析', {'demo_only': True})
    ai._call_model('key', 'model', '分析', {'demo_only': False})
    assert ai._DEMO_SYSTEM in payloads[0]['messages'][0]['content']
    assert ai._DEMO_SYSTEM not in payloads[1]['messages'][0]['content']
    assert '不得推荐引擎结论之外的方向' in payloads[1]['messages'][0]['content']


def test_demo_direction_only_accepts_available_candidates():
    context = {'demo_only': True, 'candidates': [
        {'direction': 'S', 'available': True}, {'direction': 'NW', 'available': False},
    ]}
    assert ai._demo_direction('模拟方向：S\n理由', context) == ('S', '理由')
    assert ai._demo_direction('模拟方向：NW\n理由', context)[0] is None
    assert ai._demo_direction('模拟方向：E\n理由', context)[0] is None
    assert ai._demo_direction('模拟方向：S\n理由', {'demo_only': False})[0] is None
    assert ai._demo_direction('模拟方向：S', context)[0] is None


def test_demo_request_requires_server_switches(monkeypatch):
    monkeypatch.setenv('ADVISORY_SHOW_DEMO', '1')
    monkeypatch.delenv('ADVISORY_DEMO_CALL_MODEL', raising=False)
    app = FastAPI()
    app.state.store = Store(Settings.from_env())
    app.include_router(ai.router, prefix='/api')
    result = TestClient(app).post('/api/ai/advice', json={'message': '任务', 'scenario': 'demo'})
    assert result.status_code == 403
