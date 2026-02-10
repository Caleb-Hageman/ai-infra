from fastapi import APIRouter, UploadFile

router = APIRouter()


@router.post("/ingestOne")
async def create_file(file: UploadFile):
    contents = await file.read()
    return {"file_size": len(contents)}


@router.post("/ingest")
async def create_files(files: list[UploadFile]):
    sizes = [len(await f.read()) for f in files]
    return {"file_sizes": sizes}
