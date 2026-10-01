from marketplace_mail import (
    BuyerUpdate,
    InfraiError,
    OrderHandoff,
    SellerAsset,
    SenderRecords,
    publish,
    record_set,
)


def sample_request() -> SenderRecords:
    return SenderRecords(
        domain="mail.creators.example",
        spf="v=spf1 include:sender.example -all",
        dkim_name="news._domainkey.mail.creators.example",
        dkim_content="v=DKIM1; k=rsa; p=PUBLICKEY",
        dmarc="v=DMARC1; p=quarantine",
        handoff=OrderHandoff(
            order_id="order-42",
            seller=SellerAsset(asset_id="print-7", title="Poster download"),
            buyer_update=BuyerUpdate(audience="buyer", event="delivery"),
        ),
    )


class RecordingClient:
    def __init__(self):
        self.calls = []

    def call(self, method, path, fields, *, write=False):
        self.calls.append((method, path, fields, write))
        if path == "/v1/dns/domain/get":
            return {"zone_id": "zone-17"}
        if path == "/v1/email/domain/verify":
            return {"verification": {"status": "verified"}}
        return {}


def test_order_handoff_publishes_three_txt_records_in_resolved_zone():
    client = RecordingClient()
    result = publish(client, sample_request())

    assert result["order_id"] == "order-42"
    assert result["verification_status"] == "verified"
    assert [call[1] for call in client.calls] == [
        "/v1/dns/domain/get",
        "/v1/dns/record/upsert",
        "/v1/dns/record/upsert",
        "/v1/dns/record/upsert",
        "/v1/email/domain/verify",
    ]
    assert all(call[2]["zone_id"] == "zone-17" and call[2]["record_type"] == "TXT"
               for call in client.calls[1:4])
    assert record_set(sample_request())[2]["name"] == "_dmarc.mail.creators.example"


def test_missing_zone_is_created_before_any_record():
    class NewZoneClient(RecordingClient):
        def call(self, method, path, fields, *, write=False):
            if path == "/v1/dns/domain/get":
                self.calls.append((method, path, fields, write))
                raise InfraiError("NOT_FOUND", {"code": "NOT_FOUND"}, 404)
            if path == "/v1/dns/domain/add":
                self.calls.append((method, path, fields, write))
                return {"zone_id": "new-zone"}
            return super().call(method, path, fields, write=write)

    client = NewZoneClient()
    assert publish(client, sample_request())["zone_id"] == "new-zone"
    assert client.calls[1][:2] == ("POST", "/v1/dns/domain/add")
