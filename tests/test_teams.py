# Purpose: Teams router tests (create_team, create_project, create_api_key, list_*, revoke_api_key).
import os
from datetime import datetime, timezone
from uuid import uuid4, UUID

from app.auth import get_api_key
from app.db import get_session

from conftest import override_deps


def _fake_team(**kwargs):
    defaults = {"id": uuid4(), "name": "Test Team"}
    defaults.update(kwargs)
    return type("Team", (), defaults)()


def _fake_project(**kwargs):
    defaults = {"id": uuid4(), "team_id": uuid4(), "name": "Test Project"}
    defaults.update(kwargs)
    return type("Project", (), defaults)()


def _fake_api_key_out(**kwargs):
    defaults = {
        "id": uuid4(),
        "team_id": uuid4(),
        "status": "active",
        "created_at": datetime.now(timezone.utc),
        "revoked_at": None,
    }
    defaults.update(kwargs)
    return type("ApiKey", (), defaults)()

admin_id = UUID(os.getenv("ADMIN_TEAM_ID"))

def _admin_team(**kwargs):
    defaults = {"id": admin_id, "name": "Admin Team"}
    defaults.update(kwargs)
    return type("Team", (), defaults)()

def test_create_team_201_with_auth(app_client, fake_session, fake_api_key):
    team_id = admin_id
    team = _admin_team()
    key = fake_api_key(team_id=admin_id)
    
    async def fake_get_api_key():
        return key
    
    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(get_result=team),
    }):        
        response = app_client.post(
            "/teams", 
            json={"name": "Acme"},
            headers={"Authorization": "Bearer sk-test"},)
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Acme"
    assert "id" in data

def test_create_team_401_without_auth(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    team = _fake_team(id=team_id)
    key = fake_api_key(team_id=team_id)
    
    async def fake_get_api_key():
        return key
    
    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(get_result=team),
    }):        
        response = app_client.post(
            "/teams", 
            json={"name": "Acme"},
            headers={"Authorization": "Bearer sk-test"},)
    
    assert response.status_code == 401


def test_create_project_201_with_valid_body(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    team = _fake_team(id=team_id)
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(get_result=team),
    }):
        response = app_client.post(
            f"/teams/projects",
            json={"name": "My Project"},
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Project"
    assert data["team_id"] == str(team_id)
    assert "id" in data


def test_create_api_key_401_without_auth(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    team = _fake_team(id=team_id)
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_session: fake_session(get_result=team),
        get_api_key: fake_get_api_key,
        }):
        response = app_client.post(
            f"/teams/{team_id}/api-keys",
            headers={"Authorization": "Bearer sk-test"},)
    assert response.status_code == 401

def test_create_api_key_201_with_auth(app_client, fake_session, fake_api_key):
    team_id = admin_id
    team = _admin_team()
    key = fake_api_key(team_id=admin_id)
    
    async def fake_get_api_key():
        return key

    with override_deps({
        get_session: fake_session(get_result=team),
        get_api_key: fake_get_api_key,
        }):
        response = app_client.post(
            f"/teams/{team_id}/api-keys",
            headers={"Authorization": "Bearer sk-test"},)
    assert response.status_code == 201
    data = response.json()
    assert data["team_id"] == str(team_id)
    assert "id" in data
    assert data["key"].startswith("sk-")
    assert "created_at" in data


def test_list_teams_200_with_mocked_data(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    team = _fake_team(team_id=team_id, name="Acme")
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(execute_result=[team]),
    }):
        response = app_client.get("/teams", headers={"Authorization": "Bearer sk-test"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Acme"


def test_list_projects_200_with_mocked_data(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    project = _fake_project(team_id=team_id, name="Proj A")
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(execute_result=[project]),
    }):
        response = app_client.get(
            f"/teams/projects",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Proj A"


def test_list_api_keys_200_with_mocked_data(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    api_key = _fake_api_key_out(team_id=team_id)
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(execute_result=[api_key]),
    }):
        response = app_client.get(
            f"/teams/{team_id}/api-keys",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "active"


def test_revoke_api_key_403_when_key_not_in_team(app_client, fake_session, fake_api_key):
    team_id = uuid4()
    other_team_id = uuid4()
    api_key = _fake_api_key_out(id=uuid4(), team_id=team_id)
    key = fake_api_key(team_id=other_team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(get_result=api_key),
    }):
        response = app_client.delete(
            f"/teams/{team_id}/api-keys/{api_key.id}",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 403


def test_revoke_api_key_200_when_revoked(app_client, fake_session, fake_api_key):
    from app.models import ApiKeyStatus

    team_id = uuid4()
    key_id = uuid4()
    api_key = _fake_api_key_out(id=key_id, team_id=team_id, status=ApiKeyStatus.active)
    api_key.status = ApiKeyStatus.active
    key = fake_api_key(team_id=team_id)

    async def fake_get_api_key():
        return key

    with override_deps({
        get_api_key: fake_get_api_key,
        get_session: fake_session(get_result=api_key),
    }):
        response = app_client.delete(
            f"/teams/{team_id}/api-keys/{key_id}",
            headers={"Authorization": "Bearer sk-test"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "revoked"
