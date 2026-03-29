from fastapi import FastAPI

from .routers import chat, ingest, query, teams, metrics

app = FastAPI()

app.add_middleware(metrics.ApiUsageMiddleware)

app.include_router(teams.router)
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(chat.router)


@app.get("/")
async def root():
    return {"message": "hello world"}
