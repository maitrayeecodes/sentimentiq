import io
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.services.reporting import next_run, build_pdf_report
from datetime import datetime, timezone

client = TestClient(app)

def create_account():
    email = f'{uuid.uuid4().hex}@example.com'
    response = client.post('/api/v1/auth/register', json={
        'full_name': 'Report Tester', 'email': email,
        'password': 'correct-horse-battery-42', 'workspace_name': 'Reporting workspace'
    })
    assert response.status_code == 201, response.text
    body = response.json()
    return {'Authorization': f"Bearer {body['access_token']}", 'X-Workspace-ID': body['active_workspace_id']}

def create_analysis(headers):
    response = client.post('/api/v1/analyses', headers=headers,
        files={'file': ('feedback.csv', io.BytesIO(b'review_text\n"Excellent product quality and fast delivery"\n"Terrible delivery and damaged packaging"\n'), 'text/csv')},
        data={'dataset_name': 'Reporting test dataset'})
    assert response.status_code == 201, response.text
    return response.json()['id']

def test_pdf_report_download_is_workspace_scoped():
    headers = create_account()
    analysis_id = create_analysis(headers)
    response = client.get(f'/api/v1/reports/{analysis_id}.pdf', headers=headers)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/pdf')
    assert response.content.startswith(b'%PDF')
    other = create_account()
    assert client.get(f'/api/v1/reports/{analysis_id}.pdf', headers=other).status_code == 404

def test_schedule_create_run_delivery_and_download(monkeypatch):
    monkeypatch.delenv('SMTP_HOST', raising=False)
    headers = create_account()
    analysis_id = create_analysis(headers)
    response = client.post('/api/v1/report-schedules', headers=headers, json={
        'analysis_id': analysis_id, 'recipient_email': 'owner@example.com',
        'cadence': 'weekly', 'hour_utc': 9, 'day_of_week': 0,
        'negative_alert_threshold': 30
    })
    assert response.status_code == 201, response.text
    schedule_id = response.json()['id']
    # A recurring schedule should follow the newest saved run with the same dataset name.
    newer_analysis_id = create_analysis(headers)
    assert response.json()['next_run_at']
    other_workspace = create_account()
    assert client.get('/api/v1/report-schedules', headers=other_workspace).json() == []
    listed = client.get('/api/v1/report-schedules', headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1
    run = client.post(f'/api/v1/report-schedules/{schedule_id}/run', headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()['status'] == 'generated_not_sent'
    delivery_id = run.json()['id']
    assert '[Sentiment alert]' in client.get('/api/v1/report-deliveries', headers=headers).json()[0]['subject']
    assert client.get('/api/v1/report-deliveries', headers=headers).json()[0]['analysis_id'] == newer_analysis_id
    delivery = client.get(f'/api/v1/report-deliveries/{delivery_id}.pdf', headers=headers)
    assert delivery.status_code == 200 and delivery.content.startswith(b'%PDF')
    other = create_account()
    assert client.get(f'/api/v1/report-deliveries/{delivery_id}.pdf', headers=other).status_code == 404
    assert len(client.get('/api/v1/report-deliveries', headers=headers).json()) == 1
    assert client.delete(f'/api/v1/report-schedules/{schedule_id}', headers=headers).status_code == 204

def test_next_run_uses_utc_and_weekday():
    now = datetime(2026, 11, 13, 8, 30, tzinfo=timezone.utc)  # Friday
    monday = next_run('weekly', 9, 0, 1, now)
    assert monday.weekday() == 0
    assert monday.hour == 9
    assert monday > now
    monthly = next_run('monthly', 9, 0, 1, now)
    assert monthly.day == 1 and monthly.hour == 9 and monthly > now

def test_pdf_escapes_untrusted_dataset_and_review_text():
    pdf = build_pdf_report({'dataset_name': '<script>alert(1)</script>', 'total_reviews': 0,
        'sentiment_distribution': {}, 'insights': [{'title': '<unsafe>', 'evidence': 'A & B'}],
        'topics': [], 'complaints': [], 'methodology': 'Test & validate'})
    assert pdf.startswith(b'%PDF')
