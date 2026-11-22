from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import program
from app.services import weather_reference as weather


def test_device_location_queries_district_without_changing_default(monkeypatch):
    calls = []
    now = datetime.now(timezone.utc).astimezone(weather._SHANGHAI)
    def request(url, params):
        calls.append((url, params))
        if 'convert' in url:
            return {'status': '1', 'locations': '116.400000,39.900000'}
        if 'regeo' in url:
            return {'status': '1', 'regeocode': {'addressComponent': {
                'province': '北京', 'city': [], 'district': '东城区', 'adcode': '110101'}}}
        return {'status': '1', 'lives': [{'adcode': '110101',
            'reporttime': now.strftime('%Y-%m-%d %H:%M:%S'), 'weather': '晴',
            'temperature': '20', 'winddirection': '北', 'windpower': '小于3', 'humidity': '50'}]}
    monkeypatch.setattr(weather, '_key', lambda: 'test-key')
    monkeypatch.setattr(weather, '_request', request)
    default = weather.WeatherReference()
    app = FastAPI()
    app.include_router(program.router, prefix='/api')
    response = TestClient(app).post('/api/weather/device', json={'latitude': 39.9, 'longitude': 116.4})
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == 'current'
    assert result['data']['adcode'] == '110101'
    assert '东城区' in result['data']['location']
    assert calls[0][1]['coordsys'] == 'gps'
    assert default.adcode == '500108' and default.snapshot()['data'] is None
    assert 'latitude' not in result['data'] and 'longitude' not in result['data']
    assert TestClient(app).post('/api/weather/device', json={'latitude': 91, 'longitude': 0}).status_code == 422


def test_device_location_provider_failure_does_not_expose_key(monkeypatch):
    monkeypatch.setattr(weather, '_key', lambda: 'secret')
    def fail(*args):
        raise OSError('secret')
    monkeypatch.setattr(weather, '_request', fail)
    result = weather.locate_weather(29.5, 106.5)
    assert result == {'status': 'unavailable', 'reason': 'fetch_failed', 'data': None}
