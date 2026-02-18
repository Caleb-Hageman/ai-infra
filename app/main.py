from fastapi import FastAPI

from .routers import ingest, query

app = FastAPI()
#app.include_router(teams.router)
app.include_router(ingest.router)
app.include_router(query.router)


@app.get("/")
async def root():
    return {"message": "hello world"}
