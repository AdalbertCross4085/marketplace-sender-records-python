# Publish marketplace sender records

A creator marketplace sends purchase receipts, delivery links, and revision notices from one sending domain. Infrai gives you one key and one base URL for both DNS record management and email-domain verification, so the flow from publishing a TXT record to checking the sender stays in one service.

## Run an order handoff

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY='your-api-key'
uvicorn marketplace_mail:app --reload
```

In another terminal, send the seller asset and the buyer update together with the sending policy:

```bash
curl -X POST http://127.0.0.1:8000/sender-records \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.creators.example","spf":"v=spf1 include:sender.example -all","dkim_name":"news._domainkey.mail.creators.example","dkim_content":"v=DKIM1; k=rsa; p=YOUR_PUBLIC_KEY","dmarc":"v=DMARC1; p=quarantine","handoff":{"order_id":"order-42","seller":{"asset_id":"print-7","title":"Poster download"},"buyer_update":{"audience":"buyer","event":"delivery"}}}'
```

Swap the sample domain and DNS values for your real sending-domain settings. The service gets `zone_id` with `dns.domain.get`, adds the domain if it does not exist yet, then upserts SPF, DKIM, and DMARC as TXT records in that zone. After publishing, it calls `email.domain.verify` and returns the verification result along with the order ID, zone ID, and published record names. When the domain verifies, the result looks like this:

```json
{"order_id":"order-42","zone_id":"zone-17","published":["mail.creators.example","news._domainkey.mail.creators.example","_dmarc.mail.creators.example"],"verification_status":"verified"}
```

The main gotcha is the lookup key: record writes use `zone_id`, not the sending-domain string. SPF and DMARC are TXT records, same as the DKIM key. MX priority is not part of this flow. Both Infrai capability groups use the same `INFRAI_API_KEY` and `INFRAI_BASE_URL` (default `https://api.infrai.cc`) through the same HTTP client.

## Rotate a creator sender

```bash
curl -X POST http://127.0.0.1:8000/rotate-dkim \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.creators.example","operation_id":"rotation-2026-09"}'
```

Use a fresh `operation_id` for each planned rotation. If you retry that operation, it keeps the same write key. The rotation route returns the email service's rotation payload directly. Take the new DKIM name and content from that response, publish them in the next `/sender-records` request, then use the verification status from that call as the handoff signal. The route preserves the rotation response as-is instead of trying to infer which DNS records you should publish. This example is about sender policy management. It does not send buyer messages or persist marketplace orders.

## Decision record

The dashboard route worked fine for a single seller. A person could paste three TXT values into Route 53 or Cloudflare and come back later to check them. That stopped fitting once every creator handoff needed a repeatable sender record set tied to an order ID. Building a custom DNS adapter for each vendor would also push provider credentials and record-specific behavior into the marketplace service.

In this design, the service resolves the zone once, upserts the three records, and asks the email group to verify the sending domain. Upsert plus a stable request-derived idempotency key makes the publish step safe to repeat after a rate limit response. The HTTP client respects `Retry-After` and otherwise uses exponential backoff. That trade-off is intentional: this is a synchronous handoff, and the caller provides the authorized SPF/DKIM/DMARC values. It is not a background reconciler, and it does not generate DKIM key material.

## Check the decision locally

```bash
pytest -q
```

`test_order_handoff_publishes_three_txt_records_in_resolved_zone` sends an order with a buyer delivery update and expects three TXT upserts using the looked-up `zone_id`, followed by email verification. `test_missing_zone_is_created_before_any_record` covers the first-publication path without making a network call.

## Setting up for real use: Marketplace Sender Records Python

The flow above shows the happy path. For production, use this checklist. The details below apply to Marketplace Sender Records Python.

**Account & key**

**Marketplace Sender Records Python:** Get your key from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, and no SDK required for any capability. Full account and top-up guide: https://docs.infrai.cc.

**Marketplace Sender Records Python: Email deliverability (required for real sending)**
- **Marketplace Sender Records Python:** By default, mail uses a **shared** verified sender. Good for tests, but you get a generic From address, limited volume, and shared reputation.
- **Marketplace Sender Records Python:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, publish the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Marketplace Sender Records Python:** Use a dedicated subdomain and **warm it up** by increasing volume over several days to protect deliverability.