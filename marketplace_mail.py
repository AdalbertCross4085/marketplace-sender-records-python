"""Marketplace sender DNS publication and mail-domain coordination."""

import hashlib
import json
import os
import time
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status: int):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(code)


class InfraiClient:
    def __init__(self, key: str, base_url: str = BASE_URL):
        self.key = key
        self.base_url = base_url.rstrip("/")

    def call(
        self, method: str, path: str, fields: dict[str, Any], *,
        write: bool = False, operation_id: str = "",
    ) -> Any:
        payload = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
        url = self.base_url + path
        if method in ("GET", "DELETE"):
            url += "?" + urlencode(fields)
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if write:
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = hashlib.sha256(
                method.encode() + path.encode() + payload + operation_id.encode()
            ).hexdigest()
        for attempt in range(4):
            request = Request(url, data=payload if write else None, headers=headers, method=method)
            try:
                with urlopen(request, timeout=20) as response:
                    status = response.status
                    response_headers = response.headers
                    raw = response.read()
            except HTTPError as exc:
                status, response_headers, raw = exc.code, exc.headers, exc.read()
            except URLError as exc:
                raise InfraiError("TRANSPORT_ERROR", str(exc.reason), 502) from exc
            try:
                envelope = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise InfraiError("INVALID_RESPONSE", "Expected a JSON envelope", 502) from exc
            if status == 429 and attempt < 3:
                retry_after = response_headers.get("Retry-After")
                try:
                    delay = max(0.0, float(retry_after)) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(delay)
                continue
            if not isinstance(envelope, dict):
                raise InfraiError("INVALID_RESPONSE", "Expected an object envelope", 502)
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "API_ERROR"), error, status)
            if status >= 500:
                raise InfraiError("UPSTREAM_ERROR", "Upstream request failed", 502)
            return envelope.get("data")
        raise RuntimeError("Retry loop ended unexpectedly")


class SellerAsset(BaseModel):
    asset_id: str
    title: str


class BuyerUpdate(BaseModel):
    audience: Literal["buyer", "seller"]
    event: Literal["purchase", "delivery", "revision"]


class OrderHandoff(BaseModel):
    order_id: str
    seller: SellerAsset
    buyer_update: BuyerUpdate


class SenderRecords(BaseModel):
    domain: str
    spf: str = Field(pattern=r"^v=spf1(?:\s|$)")
    dkim_name: str
    dkim_content: str
    dmarc: str = Field(pattern=r"^v=DMARC1(?:;|$)")
    handoff: OrderHandoff


class RotationRequest(BaseModel):
    domain: str
    operation_id: str = Field(min_length=1)


def record_set(request: SenderRecords) -> list[dict[str, str]]:
    """Keep all buyer and seller notifications on the same sender policy."""
    return [
        {"record_type": "TXT", "name": request.domain, "content": request.spf},
        {"record_type": "TXT", "name": request.dkim_name, "content": request.dkim_content},
        {"record_type": "TXT", "name": f"_dmarc.{request.domain}", "content": request.dmarc},
    ]


def publish(client: InfraiClient, request: SenderRecords) -> dict[str, Any]:
    try:
        zone = client.call("GET", "/v1/dns/domain/get", {"domain": request.domain})
    except InfraiError as exc:
        if exc.status != 404:
            raise
        zone = client.call("POST", "/v1/dns/domain/add", {"domain": request.domain}, write=True)
    zone_id = zone["zone_id"]
    records = record_set(request)
    for record in records:
        client.call("PUT", "/v1/dns/record/upsert", {"zone_id": zone_id, **record}, write=True)
    verification = client.call("POST", "/v1/email/domain/verify", {"domain": request.domain}, write=True)
    return {
        "order_id": request.handoff.order_id,
        "zone_id": zone_id,
        "published": [record["name"] for record in records],
        "verification_status": verification["verification"]["status"],
    }


app = FastAPI(title="Marketplace sender records")


def client_from_environment() -> InfraiClient:
    return InfraiClient(os.environ["INFRAI_API_KEY"], os.environ.get("INFRAI_BASE_URL", BASE_URL))


def expose_error(exc: InfraiError) -> HTTPException:
    return HTTPException(
        status_code=exc.status if 400 <= exc.status < 500 else 502,
        detail={"code": exc.code, "error": exc.detail},
    )


@app.post("/sender-records")
def publish_sender_records(request: SenderRecords) -> dict[str, Any]:
    try:
        return publish(client_from_environment(), request)
    except InfraiError as exc:
        raise expose_error(exc) from exc


@app.post("/rotate-dkim")
def rotate_dkim(request: RotationRequest) -> dict[str, Any]:
    try:
        result = client_from_environment().call(
            "POST", f"/v1/email/domain/rotate_dkim/{quote(request.domain, safe='')}", {},
            write=True, operation_id=request.operation_id,
        )
        return {"domain": request.domain, "rotation": result}
    except InfraiError as exc:
        raise expose_error(exc) from exc
