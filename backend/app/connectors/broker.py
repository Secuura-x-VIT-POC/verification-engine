from app.connectors.vit_mock import verify as vit_verify
from app.connectors.vc_mock import verify as vc_verify

def call_connector(data: dict, connector: str = "vit"):

    if connector == "vit":
        return vit_verify(data)

    elif connector == "vc":
        return vc_verify(data)

    else:
        raise ValueError("Unknown connector")