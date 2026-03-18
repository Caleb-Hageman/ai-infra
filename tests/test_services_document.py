# Purpose: Document service unit tests (create_uploaded_document).

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.services.document import create_uploaded_document


async def test_create_uploaded_document_adds_and_commits():
    async def mock_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()

    session = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(side_effect=mock_refresh)

    team_id = uuid4()
    project_id = uuid4()
    doc = await create_uploaded_document(
        session=session,
        team_id=team_id,
        project_id=project_id,
        filename="test.pdf",
        gcs_path="team/proj/test.pdf",
        mime_type="application/pdf",
    )

    assert doc.team_id == team_id
    assert doc.project_id == project_id
    assert doc.title == "test.pdf"
    assert doc.gcs_uri == "team/proj/test.pdf"
    session.add.assert_called_once()
    session.commit.assert_called_once()
    session.refresh.assert_called_once()
