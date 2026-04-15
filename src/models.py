from typing import Literal, Optional

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    action: Literal[
        "turn_on",
        "turn_off",
        "change_source",
        "switch_to_game_mode",
        "switch_to_default_mode",
    ] = Field(
        ...,
        description=(
            "Action to perform.\n\n"
            "- **turn_on**: Accepted for upstream API compatibility but not supported by the PC bridge\n"
            "- **turn_off**: Accepted for upstream API compatibility but not supported by the PC bridge\n"
            "- **change_source**: Accepted for upstream API compatibility but not supported by the PC bridge\n"
            "- **switch_to_game_mode**: Enter PC gaming mode\n"
            "- **switch_to_default_mode**: Leave PC gaming mode"
        ),
    )
    target: Optional[str] = Field(
        default=None,
        description=(
            "Target source.\n\n"
            "Accepted for upstream API compatibility but ignored by the PC bridge.\n"
            "Only present so clients using the Raspberry Pi schema can reuse the same payload shape."
        ),
    )


class ActionResponse(BaseModel):
    ok: bool
    action: str
    gaming_mode_active: bool
    trigger: str
    steps: list[dict]


class CertInfo(BaseModel):
    suggested_base_url: Optional[str]
    sha256_fingerprint: str
    pem: str
