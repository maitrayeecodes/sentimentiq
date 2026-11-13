import io
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.storage import init_db

init_db()
client = TestClient(app)

def account(email):
    response = client.post('/api/v1/auth/register', json={
        'full_name': 'Test User', 'email': email,
        'password': 'correct-horse-battery-42', 'workspace_name': 'Workspace ' + email.split('@')[0]
    })
    assert response.status_code == 201, response.text
    data = response.json()
    return data['access_token'], data['active_workspace_id']

def test_register_login_and_protected_endpoint():
    email = f'{uuid.uuid4().hex}@example.com'
    token, workspace = account(email)
    assert client.get('/api/v1/analyses').status_code == 401
    me = client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == 200
    assert me.json()['user']['email'] == email
    login = client.post('/api/v1/auth/login', json={'email': email, 'password': 'correct-horse-battery-42'})
    assert login.status_code == 200
    assert login.json()['active_workspace_id'] == workspace

def test_analysis_isolated_between_workspaces():
    token_a, workspace_a = account(f'{uuid.uuid4().hex}@example.com')
    token_b, workspace_b = account(f'{uuid.uuid4().hex}@example.com')
    csv_bytes = b'review_text,rating\n"Excellent product quality",5\n"Terrible delivery delay",1\n'
    headers_a = {'Authorization': f'Bearer {token_a}', 'X-Workspace-ID': workspace_a}
    upload = client.post('/api/v1/analyses', headers=headers_a,
        files={'file': ('reviews.csv', io.BytesIO(csv_bytes), 'text/csv')}, data={'dataset_name': 'Tenant A'})
    assert upload.status_code == 201, upload.text
    analysis_id = upload.json()['id']
    headers_b = {'Authorization': f'Bearer {token_b}', 'X-Workspace-ID': workspace_b}
    assert client.get('/api/v1/analyses', headers=headers_b).json() == []
    assert client.get(f'/api/v1/analyses/{analysis_id}', headers=headers_b).status_code == 404
    assert client.get(f'/api/v1/analyses/{analysis_id}', headers=headers_a).status_code == 200

def test_invalid_password_is_rejected():
    email = f'{uuid.uuid4().hex}@example.com'
    account(email)
    response = client.post('/api/v1/auth/login', json={'email': email, 'password': 'wrong-password'})
    assert response.status_code == 401

def test_excel_xlsx_upload_and_aspect_sentiment():
    from openpyxl import Workbook
    output = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['review_id', 'review_text', 'rating', 'date'])
    sheet.append(['X001', 'Delivery was late. Product quality is excellent.', 3, '2026-11-01'])
    workbook.save(output)
    output.seek(0)
    token, workspace = account(f'{uuid.uuid4().hex}@example.com')
    headers = {'Authorization': f'Bearer {token}', 'X-Workspace-ID': workspace}
    response = client.post('/api/v1/analyses', headers=headers,
        files={'file': ('reviews.xlsx', output, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        data={'dataset_name': 'Excel test'})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['total_reviews'] == 1
    aspects = {item['topic']: item for item in result['reviews'][0]['aspect_sentiments']}
    assert 'Delivery' in aspects and 'Product Quality' in aspects
    assert aspects['Delivery']['sentiment'] == 'Negative'
    assert aspects['Product Quality']['sentiment'] == 'Positive'
    assert result['topics']
    assert all('recommended_action' in item for item in result['topics'])
    assert 'emotion_distribution' in result and 'priority_distribution' in result
    assert 'duplicate_summary' in result and 'emerging_terms' in result
    assert result['reviews'][0]['urgency']['priority'] in ('Critical', 'High', 'Medium', 'Low')


def test_unsupported_file_type_is_rejected():
    token, workspace = account(f'{uuid.uuid4().hex}@example.com')
    headers = {'Authorization': f'Bearer {token}', 'X-Workspace-ID': workspace}
    response = client.post('/api/v1/analyses', headers=headers,
        files={'file': ('reviews.xls', io.BytesIO(b'not supported'), 'application/octet-stream')})
    assert response.status_code == 415


def test_csv_upload_with_ground_truth_returns_evaluation_and_language_signals():
    token, workspace = account(f'{uuid.uuid4().hex}@example.com')
    headers = {'Authorization': f'Bearer {token}', 'X-Workspace-ID': workspace}
    csv_bytes = (
        b'review_text,expected_sentiment\n'
        b'"La entrega fue terrible y el producto es malo",Negative\n'
        b'"La livraison et le produit sont excellents",Positive\n'
        b'"The product quality is excellent",Positive\n'
    )
    response = client.post('/api/v1/analyses', headers=headers,
        files={'file': ('labelled.csv', io.BytesIO(csv_bytes), 'text/csv')})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['model_evaluation']['sample_size'] == 3
    assert result['language_distribution']['es'] == 1
    assert result['language_distribution']['fr'] == 1
    assert result['similar_review_clusters']

def test_competitive_benchmark_compares_only_selected_workspace_datasets():
    token, workspace = account(f'{uuid.uuid4().hex}@example.com')
    headers = {'Authorization': f'Bearer {token}', 'X-Workspace-ID': workspace}
    def upload(name, content):
        response = client.post('/api/v1/analyses', headers=headers,
            files={'file': ('reviews.csv', io.BytesIO(content), 'text/csv')},
            data={'dataset_name': name})
        assert response.status_code == 201, response.text
        return response.json()['id']
    brand_a = upload('Brand A', b'review_text\n"Excellent product quality and amazing support"\n"Great delivery and helpful staff"\n')
    brand_b = upload('Brand B', b'review_text\n"Terrible product quality and poor support"\n"Late delivery and damaged package"\n')
    response = client.post('/api/v1/competitive/benchmark', headers=headers,
        json={'analysis_ids': [brand_a, brand_b]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['dataset_count'] == 2
    assert {d['brand'] for d in result['datasets']} == {'Brand A', 'Brand B'}
    assert result['datasets'][0]['review_count'] == 2
    assert any(t['topic'] == 'Product Quality' for t in result['topic_comparison'])
    assert result['methodology']


def test_competitive_benchmark_rejects_dataset_from_another_workspace():
    token_a, workspace_a = account(f'{uuid.uuid4().hex}@example.com')
    token_b, workspace_b = account(f'{uuid.uuid4().hex}@example.com')
    headers_a = {'Authorization': f'Bearer {token_a}', 'X-Workspace-ID': workspace_a}
    headers_b = {'Authorization': f'Bearer {token_b}', 'X-Workspace-ID': workspace_b}
    upload = client.post('/api/v1/analyses', headers=headers_a,
        files={'file': ('reviews.csv', io.BytesIO(b'review_text\n"Excellent quality"\n'), 'text/csv')})
    assert upload.status_code == 201
    foreign_id = upload.json()['id']
    response = client.post('/api/v1/competitive/benchmark', headers=headers_b,
        json={'analysis_ids': [foreign_id, foreign_id + '-missing']})
    assert response.status_code == 404
