from fastapi import FastAPI, HTTPException

from .routers import chat, ingest, query, teams, metrics

from . import warmup as warmup_mod

app = FastAPI()

app.add_middleware(metrics.ApiUsageMiddleware)

app.include_router(teams.router)
app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(chat.router)


@app.get("/")
async def root():
    return {"message": "hello world"}

@app.get("/warmup")
async def warmup():
    # Session warmup: DB, embeddings, vLLM kickoff
    status = await warmup_mod.warmup_dependencies()
    if not warmup_mod.warmup_all_ok(status):
        raise HTTPException(status_code=503, detail=status)
    return {"status": "warmed", "components": status}
