from fastapi import FastAPI, HTTPException

from app.assets import list_assets
from app.models import AssetAnalysis
from app.orchestrator import orchestrator

app = FastAPI(
    title="AgenticCore Markets — Analysis Framework",
    description="Live technical + fundamental + news signal analysis for forex pairs and crypto assets.",
    version="0.1.0",
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/assets")
async def get_assets() -> list:
    return list_assets()


@app.get("/api/v1/analysis/{symbol}", response_model=AssetAnalysis)
async def get_analysis(symbol: str) -> AssetAnalysis:
    try:
        return await orchestrator.get_analysis(symbol)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
