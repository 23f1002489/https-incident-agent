from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


class Symptom(str, Enum):
    http_4xx = 'http_4xx'
    http_5xx = 'http_5xx'
    timeout = 'timeout'
    high_latency = 'high_latency'


class IncidentCreate(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    symptom: Symptom
    description: str | None = Field(default=None, max_length=2000)


class Incident(IncidentCreate):
    id: str
    status: str
    created_at: datetime
