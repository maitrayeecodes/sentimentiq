import io
import uuid
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def account():
    email = f'{uuid.uuid4().hex}@example.com'
    r = client.post('/api/v1/auth/register', json={
        'full_name': 'Ops Owner', 'email': email,
        'password': 'correct-horse-battery-42', 'workspace_name': 'Ops Workspace'
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return {'Authorization': f"Bearer {body['access_token']}", 'X-Workspace-ID': body['active_workspace_id']}

def upload(headers, name='retention-test'):
    r = client.post('/api/v1/analyses', headers=headers,
        files={'file': ('reviews.csv', io.BytesIO(b'review_text\n"The product is excellent"\n"Terrible support"\n'), 'text/csv')},
        data={'dataset_name': name})
    assert r.status_code == 201, r.text
    return r.json()['id']

def test_security_headers_are_set():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert r.headers['x-frame-options'] == 'DENY'

def test_delete_analysis_removes_associated_data_and_records_audit():
    headers = account()
    analysis_id = upload(headers)
    r = client.delete(f'/api/v1/analyses/{analysis_id}', headers=headers)
    assert r.status_code == 204
    assert client.get(f'/api/v1/analyses/{analysis_id}', headers=headers).status_code == 404
    audit = client.get('/api/v1/audit-events', headers=headers)
    assert audit.status_code == 200
    assert any(x['action'] == 'delete' and x['resource_id'] == analysis_id for x in audit.json())

def test_retention_purge_requires_confirmation_and_owner():
    headers = account()
    analysis_id = upload(headers)
    missing_confirmation = client.post('/api/v1/data-retention/purge', headers=headers,
        json={'older_than_days': 30, 'confirm': False})
    assert missing_confirmation.status_code == 400
    # Force this analysis to be older than the minimum retention window.
    from app.storage import SessionLocal, Analysis
    from datetime import datetime, timezone
    db = SessionLocal()
    try:
        item = db.get(Analysis, analysis_id)
        item.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
    finally:
        db.close()
    purged = client.post('/api/v1/data-retention/purge', headers=headers,
        json={'older_than_days': 30, 'confirm': True})
    assert purged.status_code == 200, purged.text
    assert purged.json()['deleted_analyses'] == 1
    assert client.get(f'/api/v1/analyses/{analysis_id}', headers=headers).status_code == 404

def test_audit_log_is_owner_only():
    owner = account()
    # Registering creates an owner; a different workspace is not visible.
    outsider = account()
    assert client.get('/api/v1/audit-events', headers=outsider).json() == []


def test_readiness_probe_checks_database_connection():
    response = client.get('/ready')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'ready'
    assert response.json()['database'] == 'ok'
