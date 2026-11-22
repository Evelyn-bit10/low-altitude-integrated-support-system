from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.task_drafts import router


def client():
    app = FastAPI()
    app.include_router(router, prefix='/api')
    return TestClient(app)


def test_empty_draft_reports_missing_fields_without_operational_decision():
    response = client().post('/api/task-drafts/check', json={})
    assert response.status_code == 200
    body = response.json()
    assert len(body['missing_information']) == 6
    assert body['draft_complete'] is False
    assert body['operationally_validated'] is False
    assert body['executed'] is False


def test_complete_draft_allows_zero_weight_and_trims_text():
    response = client().post('/api/task-drafts/check', json={
        'task_id': ' T-01 ', 'aircraft_id': ' U-01 ', 'site_id': ' L-01 ',
        'operation': 'departure', 'payload_description': ' 无载荷 ', 'payload_weight_kg': 0,
    })
    assert response.status_code == 200
    body = response.json()
    assert body['draft_complete'] is True
    assert body['draft']['task_id'] == 'T-01'
    assert body['draft']['payload_weight_kg'] == 0
    assert body['operationally_validated'] is False
    assert body['executed'] is False


def test_whitespace_is_missing_and_invalid_inputs_are_rejected():
    c = client()
    response = c.post('/api/task-drafts/check', json={'task_id': '  '})
    assert response.json()['draft']['task_id'] is None
    for payload in ({'payload_weight_kg': -1}, {'operation': 'fly'},
                    {'task_id': 'a' * 101}, {'unknown': 1}):
        assert c.post('/api/task-drafts/check', json=payload).status_code == 422
