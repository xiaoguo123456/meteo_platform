from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .catalog import MODEL_CATALOG, VARIABLE_CATALOG
from .config import get_settings
from .schemas import BoundaryCollection, FieldManifest, ModelSummary


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "meteo-api"}


@app.get("/api/models", response_model=list[ModelSummary])
def models() -> list[dict[str, str]]:
    return MODEL_CATALOG


@app.get("/api/variables")
def variables() -> list[dict[str, str]]:
    return VARIABLE_CATALOG


@app.get("/api/models/{model_id}/runs")
def model_runs(model_id: str) -> dict[str, object]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return {
        "model": model_id,
        "runs": [now.isoformat(), (now.replace(hour=(now.hour - 6) % 24)).isoformat()],
    }


@app.get("/api/fields/{model_id}/{valid_time}", response_model=FieldManifest)
def field_manifest(model_id: str, valid_time: str) -> FieldManifest:
    return FieldManifest(
        model=model_id,
        run_time=datetime.now(timezone.utc).isoformat(),
        valid_time=valid_time,
        bbox=[-180, -90, 180, 90],
        width=720,
        height=361,
        variables=["u10", "v10", "temperature_2m", "surface_pressure"],
        encoding="float32-gzip",
        data_url=None,
    )


@app.get("/api/boundaries/provinces", response_model=BoundaryCollection)
def province_boundaries() -> BoundaryCollection:
    boundary_path = Path(__file__).resolve().parents[2] / "data" / "boundaries" / "provinces.geojson"
    if boundary_path.exists():
        import json

        return BoundaryCollection.model_validate(json.loads(boundary_path.read_text(encoding="utf-8")))
    return BoundaryCollection(type="FeatureCollection", features=[])
