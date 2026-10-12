from typing import Any, Optional

from pydantic import BaseModel


class ModelSummary(BaseModel):
    id: str
    name: str
    provider: str
    resolution: str
    step: str
    status: str


class FieldManifest(BaseModel):
    model: str
    run_time: str
    valid_time: str
    bbox: list[float]
    width: int
    height: int
    variables: list[str]
    encoding: str
    data_url: Optional[str] = None


class BoundaryCollection(BaseModel):
    type: str
    features: list[dict[str, Any]]
