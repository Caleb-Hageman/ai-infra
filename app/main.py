from fastapi import FastAPI

from .routers import chat, ingest, query, teams

app = FastAPI()
app.include_router(teams.router)
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(chat.router)


@app.get("/")
async def root():
    return {"message": "hello world"}
