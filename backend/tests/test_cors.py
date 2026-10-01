import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_development_cors_preflight(client: TestClient, origin: str) -> None:
    response = client.options(
        "/api/tasks/1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_other_origin_is_not_allowed(client: TestClient) -> None:
    response = client.options(
        "/api/tasks",
        headers={"Origin": "http://localhost:5174", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
