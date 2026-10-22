from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    data=response.json()
    assert data['status']=='ok'
    assert data['runtime']['protocol']=='draft-recovery-v3'
    assert data['runtime']['skills_available'] and len(data['runtime']['skill_hashes'])==7
    assert len(data['runtime']['code_hash'])==12
