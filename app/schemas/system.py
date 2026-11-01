from pydantic import BaseModel


class RootResponse(BaseModel):
    Hello: str


class HealthResponse(BaseModel):
    ok: bool
