from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from app.core.phone import normalize_phone

Phone = Annotated[str, AfterValidator(normalize_phone)]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
