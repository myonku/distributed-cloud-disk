from msgspec import Struct


class HandShakeConfirmDTO(Struct):
    verify_hmac_b64: str
    temp_hs_id: str | None = None
