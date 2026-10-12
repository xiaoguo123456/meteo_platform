from typing import Any


MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "gfs",
        "name": "GFS",
        "provider": "NOAA / Open-Meteo",
        "resolution": "0.25°",
        "step": "1 小时",
        "status": "ready",
    },
    {
        "id": "ifs",
        "name": "IFS",
        "provider": "ECMWF / Open-Meteo",
        "resolution": "0.25°",
        "step": "1 小时",
        "status": "ready",
    },
    {
        "id": "aifs",
        "name": "AIFS",
        "provider": "ECMWF / Open-Meteo",
        "resolution": "0.25°",
        "step": "6 小时",
        "status": "preview",
    },
    {
        "id": "grapes",
        "name": "GRAPES",
        "provider": "CMA / Open-Meteo",
        "resolution": "0.125°",
        "step": "3 小时",
        "status": "preview",
    },
]


VARIABLE_CATALOG = [
    {"id": "wind", "name": "风场", "unit": "m/s"},
    {"id": "temperature", "name": "温度", "unit": "°C"},
    {"id": "pressure", "name": "气压", "unit": "hPa"},
    {"id": "precipitation", "name": "降水", "unit": "mm"},
]
