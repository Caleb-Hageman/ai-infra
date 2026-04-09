# Purpose: FastAPI app root route.

def test_root_returns_message(app_client):
    response = app_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "hello world"}
