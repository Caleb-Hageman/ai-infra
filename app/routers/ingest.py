from fastapi import APIRouter, UploadFile, HTTPException
from app.services import gcs

router = APIRouter()


@router.post("/ingest/{team_id}")
async def upload_file(team_id: str, file: UploadFile):
    try:
        destination = f"{team_id}/{file.filename}"
        
        gcs_path = gcs.upload_file_stream(file.file, destination, file.content_type)
        
        return {
            "filename": file.filename, 
            "gcs_path": gcs_path,
            "status": "uploaded"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def create_files(files: list[UploadFile]):
    sizes = [len(await f.read()) for f in files]
    return {"file_sizes": sizes}
