"""Provider interface: reading and writing through a model backend (SPEC 4)."""

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel


class Provider(Protocol):
    name: str
    model: str

    def read_documents(
        self,
        images: list[Path],
        instructions: str,
        schema: dict[str, Any],
        result_model: type[BaseModel] | None = None,
    ) -> dict[str, Any]: ...

    def write(self, instructions: str, schema: dict[str, Any]) -> dict[str, Any]: ...
