from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentSourceType

async def create_uploaded_document(
    session: AsyncSession, 
    team_id: UUID, 
    project_id: UUID, 
    filename: str, 
    gcs_path: str,
    mime_type: str,
) -> Document:
    doc = Document(
        team_id=team_id,
        project_id=project_id,
        title=filename,
        source_type=DocumentSourceType.upload,
        gcs_uri=gcs_path,
        mime_type=mime_type,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc