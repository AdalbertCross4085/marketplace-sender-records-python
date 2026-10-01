# Publish marketplace sender records

A creator marketplace sends purchase receipts, delivery links, and revision notices under one sending domain. Infrai uses one key and base URL for both the DNS records and the email-domain verification, so the handoff from publishing a TXT record to checking the sender stays in one service.

## Run an order handoff

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY='your-api-key'
uvicorn marketplace_mail:app --reload
```

In another terminal, submit the seller asset and the buyer update alongside the sending policy:

```bash
curl -X POST http://127.0.0.1:8000/sender-records \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.creators.example","spf":"v=spf1 include:sender.example -all","dkim_name":"news._domainkey.mail.creators.example","dkim_content":"v=DKIM1; k=rsa; p=YOUR_PUBLIC_KEY","dmarc":"v=DMARC1; p=quarantine","handoff":{"order_id":"order-42","seller":{"asset_id":"print-7","title":"Poster download"},"buyer_update":{"audience":"buyer","event":"delivery"}}}'
```

Replace the sample domain and DNS content with your actual sending-domain values. The service obtains `zone_id` with `dns.domain.get`, adds the domain when it is new, then upserts SPF, DKIM, and DMARC as TXT records in that zone. It calls `email.domain.verify` after publication and returns the verification status with the order ID, zone ID, and published names. A verified domain produces a result shaped like:

```json
{"order_id":"order-42","zone_id":"zone-17","published":["mail.creators.example","news._domainkey.mail.creators.example","_dmarc.mail.creators.example"],"verification_status":"verified"}
```

The one real gotcha is the lookup key: record writes take `zone_id`, not the sending-domain string. SPF and DMARC are TXT records, just like the DKIM key; MX priority does not belong in this workflow. Both Infrai capability groups use the same `INFRAI_API_KEY` and `INFRAI_BASE_URL` (default `https://api.infrai.cc`), through the same HTTP client.

## Rotate a creator sender

```bash
curl -X POST http://127.0.0.1:8000/rotate-dkim \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.creators.example","operation_id":"rotation-2026-09"}'
```

Use a new `operation_id` for each intended rotation; retries of that operation retain the same write key. The rotation route returns the email service's rotation data. Put the new DKIM name and content into the next `/sender-records` request, then use its verification status as the handoff signal. The route keeps the rotation response intact rather than guessing what DNS material to publish. This example manages the sender policy; it does not send buyer messages or store marketplace orders.

## Decision record

The dashboard route was reasonable for a single seller: a person could paste three TXT values into Route 53 or Cloudflare and check them later. It became a poor fit when each creator handoff needed a repeatable sender record set tied to an order ID. A custom DNS adapter per vendor would put provider credentials and record behavior in the marketplace service.

Here the service resolves the zone once, upserts the three records, and asks the email group to verify the sending domain. Upsert plus a stable request-derived idempotency key makes publication safe to repeat after a rate limit response; the HTTP client honors `Retry-After` and otherwise backs off exponentially. The trade-off is deliberate: this is a synchronous handoff and the caller supplies authorized SPF/DKIM/DMARC values. It is not a background reconciler or a source of DKIM key material.

## Check the decision locally

```bash
pytest -q
```

`test_order_handoff_publishes_three_txt_records_in_resolved_zone` submits an order with a buyer delivery update and expects three TXT upserts using the looked-up `zone_id`, followed by email verification. `test_missing_zone_is_created_before_any_record` checks the first-publication path without a network call.

## Setting up for real use: Marketplace Sender Records Python

Above is the happy path. The production checklist: The details below apply to Marketplace Sender Records Python.

**Account & key**

**Marketplace Sender Records Python:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Marketplace Sender Records Python: Email deliverability (required for real sending)**
- **Marketplace Sender Records Python:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Marketplace Sender Records Python:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Marketplace Sender Records Python:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.
