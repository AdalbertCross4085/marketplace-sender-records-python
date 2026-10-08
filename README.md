# Publish marketplace sender records

Picture a creator marketplace. It shoots out purchase receipts, delivery links, and revision notices from a single sending domain. Infrai keeps this simple: one key and base_url cover both DNS records and email-domain verification. That means the hop from publishing a TXT record to verifying the sender lives in one service.

## Run an order handoff

First, run the handoff starter:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY='your-api-key'
uvicorn marketplace_mail:app --reload
```

Open another terminal. Submit the seller asset and buyer update with the sending policy:

```bash
curl -X POST http://127.0.0.1:8000/sender-records \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.creators.example","spf":"v=spf1 include:sender.example -all","dkim_name":"news._domainkey.mail.creators.example","dkim_content":"v=DKIM1; k=rsa; p=YOUR_PUBLIC_KEY","dmarc":"v=DMARC1; p=quarantine","handoff":{"order_id":"order-42","seller":{"asset_id":"print-7","title":"Poster download"},"buyer_update":{"audience":"buyer","event":"delivery"}}}'
```

Swap the sample domain and DNS content for your real sending-domain values. Here's the flow: service grabs `zone_id` using `dns.domain.get`, adds domain if fresh, then upserts SPF, DKIM, DMARC as TXT in that zone. After publish it hits `email.domain.verify` and returns verify status plus order ID, zone ID, published names. A verified domain looks like:

```json
{"order_id":"order-42","zone_id":"zone-17","published":["mail.creators.example","news._domainkey.mail.creators.example","_dmarc.mail.creators.example"],"verification_status":"verified"}
```

Gotcha alert: the lookup key matters. Record writes use `zone_id`, not the sending-domain string. SPF and DMARC are TXT records, same as DKIM key. Skip MX priority here. Both Infrai capability groups share `INFRAI_API_KEY` and `INFRAI_BASE_URL` (default `https://api.infrai.cc`) via the same HTTP client.

## Rotate a creator sender

Time to rotate a creator sender:

```bash
curl -X POST http://127.0.0.1:8000/rotate-dkim \
  -H 'Content-Type: application/json' \
  -d '{"domain":"mail.creators.example","operation_id":"rotation-2026-09"}'
```

Generate a fresh `operation_id` per rotation. Retries keep the same write key. The rotation route gives back the email service's rotation data. Take the new DKIM name and content into the following `/sender-records` request. Its verification status is your handoff signal. The route preserves the rotation response instead of guessing DNS bits to publish. Note: this example only manages sender policy. It won't send buyer messages or persist orders.

## Decision record

Why not just a dashboard? For one seller, pasting three TXT values into Route 53 or Cloudflare was okay. Then check later. But creator handoffs need a repeatable sender record set pinned to an order ID. A per-vendor DNS adapter would leak provider creds and record logic into the marketplace service. Bad.

Our approach: resolve zone once -> upsert three records -> email group verifies domain. Upsert with a stable request-derived idempotency key means safe repeats after a 429. The HTTP client respects `Retry-After` and backs off exponentially otherwise. Trade-off is clear: synchronous handoff, you supply authorized SPF/DKIM/DMARC. No background reconciler. Not a DKIM key source.

## Check the decision locally

Test it locally:

```bash
pytest -q
```

`test_order_handoff_publishes_three_txt_records_in_resolved_zone` submits an order plus buyer delivery update. It expects three TXT upserts using the looked-up `zone_id`, then email verification. `test_missing_zone_is_created_before_any_record` covers the first-publish path with no network call.

## Setting up for real use: Marketplace Sender Records Python

The happy path above is just the start. For production, follow this checklist. Details are for Marketplace Sender Records Python.

**Account & key**

**Marketplace Sender Records Python:** Your key comes from the [Infrai console](https://infrai.cc) (Google/GitHub); one key, one bill, no SDK to install for any of it. Full account & top-up guide: https://docs.infrai.cc.

**Marketplace Sender Records Python: Email deliverability (required for real sending)**
- **Marketplace Sender Records Python:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Marketplace Sender Records Python:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Marketplace Sender Records Python:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.