"""Shared service catalog for the data generators: teams, incident templates, base metrics, dependencies."""

# incident templates per service: (team, [(summary, root cause, error log message)], info lines, warn lines)
S = {
 "payments": ("Payments-Platform", [
   ("Payments API returning 5xx", "Bad deploy of payments-api", "503 upstream unavailable pod=payments-{n}"),
   ("Card authorisation timeouts", "Slow card network response", "timeout calling card network after 30000ms"),
   ("Duplicate charge reports", "Retry bug in charge handler", "duplicate charge request id={n}"),
   ("Refund jobs stuck in queue", "Expired queue credentials", "refund worker auth failed: credential expired")],
   ["payment {n} authorised in {ms}ms", "refund {n} processed", "settlement batch {n} completed"],
   ["card network latency p95={ms}ms", "retry attempt 2 for charge {n}"]),
 "checkout": ("Checkout-Experience", [
   ("Checkout latency spike overnight", "Database connection pool too small", "db connection pool exhausted (max=50)"),
   ("Cart totals incorrect", "Stale promo cache", "promo cache returned stale discount for cart {n}"),
   ("Checkout page fails to load", "CDN misconfiguration", "static asset 404 /checkout/app.js"),
   ("Gift card redemption failing", "Expired gift card API key", "gift card service returned 401")],
   ["order {n} placed", "cart {n} saved", "promo applied to cart {n}"],
   ["cart service p95={ms}ms", "connection pool usage at 85%"]),
 "search": ("Search-Relevance", [
   ("Search results slow for some users", "Index shard 3 under-provisioned", "query timeout on shard 3 after 5000ms"),
   ("Search returns no results for common terms", "Corrupt index segment", "index segment 17 failed checksum"),
   ("Autocomplete suggestions missing", "Suggest service outage", "suggest service unreachable"),
   ("Filters not applied to results", "Bad ranking config release", "facet filter ignored: config v{n}")],
   ["query served in {ms}ms", "index refresh completed", "autocomplete served in {ms}ms"],
   ["p95={ms}ms, index shard 3 slow", "index refresh took {ms}ms"]),
 "auth": ("Identity-Access", [
   ("Users cannot sign in", "Expired signing key", "token signature validation failed"),
   ("MFA codes not delivered", "SMS provider outage", "sms provider returned 503"),
   ("Session timeouts too short", "Wrong session TTL config", "session ttl misconfigured: 60s"),
   ("Password reset emails delayed", "Email queue backlog", "email queue depth above 5000")],
   ["login success for user {n}", "token issued in {ms}ms", "session refreshed"],
   ["failed login burst from ip 10.0.{n}.7", "token validation p95={ms}ms"]),
 "inventory": ("Supply-Chain-Systems", [
   ("Stock counts out of sync", "Delayed warehouse sync job", "warehouse sync lag 40m"),
   ("Items shown in stock but unavailable", "Cache not invalidated after sale", "inventory cache stale for sku {n}"),
   ("Reservation service errors", "Lock contention in reservations table", "deadlock detected on reservations"),
   ("Negative stock levels reported", "Race condition in decrement", "stock level below zero for sku {n}")],
   ["stock updated for sku {n}", "reservation {n} confirmed", "warehouse sync completed"],
   ["sync lag 5m", "reservation retry for sku {n}"]),
 "catalog": ("Catalog-Content", [
   ("Product images missing", "Image bucket permissions changed", "image fetch 403 for sku {n}"),
   ("Wrong prices displayed", "Pricing feed import error", "price feed row {n} rejected"),
   ("Product pages slow", "Unindexed query on product table", "slow query 4200ms on products"),
   ("New items not appearing", "Publish pipeline stalled", "publish job {n} stalled")],
   ["product {n} updated", "price feed imported", "image resized for sku {n}"],
   ["image resize took {ms}ms", "price feed delayed {n}s"]),
 "notifications": ("Messaging-Platform", [
   ("Order emails not sent", "Mail provider rate limiting", "mail provider returned 429 too many requests"),
   ("Duplicate push notifications", "Retry without idempotency key", "duplicate push for user {n}"),
   ("SMS alerts delayed", "Queue consumer scaled to zero", "sms queue depth above 3000"),
   ("Notification preferences not saved", "Schema migration missed", "column pref_json missing")],
   ["email {n} sent", "push {n} delivered", "sms {n} sent"],
   ["queue depth {n}", "provider latency p95={ms}ms"]),
 "shipping": ("Fulfilment-Logistics", [
   ("Tracking numbers missing", "Carrier API change", "carrier api returned unexpected field format"),
   ("Shipping rates wrong at checkout", "Outdated rate table", "rate table version mismatch"),
   ("Label printing failures", "Printer service certificate expired", "label service tls handshake failed"),
   ("Delivery estimates inaccurate", "Bad ETA model deploy", "eta model v{n} returned null")],
   ["label {n} printed", "tracking updated for shipment {n}", "rate quote returned in {ms}ms"],
   ["carrier api latency p95={ms}ms", "rate quote retry for shipment {n}"]),
}
TEAM = {k: v[0] for k, v in S.items()}

# service metadata for the CMDB and for the baseline metrics (cpu %, memory %, p95 latency ms, error rate %, requests/min)
META = {
    "payments":      dict(display="Payments", tier=1, bu="Commerce", desc="Card payments, refunds and settlement",
                          aliases=["payment", "payments-api", "payment gateway", "pay"],
                          base=dict(cpu=42, mem=58, lat=210, err=0.25, rpm=1800)),
    "checkout":      dict(display="Checkout", tier=1, bu="Commerce", desc="Cart, promotions and order placement",
                          aliases=["cart", "checkout-web", "order flow"],
                          base=dict(cpu=48, mem=61, lat=340, err=0.30, rpm=2400)),
    "search":        dict(display="Search", tier=1, bu="Commerce", desc="Site search, autocomplete and filters",
                          aliases=["site search", "search-api"],
                          base=dict(cpu=55, mem=66, lat=180, err=0.20, rpm=5200)),
    "auth":          dict(display="Authentication", tier=1, bu="Platform", desc="Sign-in, tokens, MFA and sessions",
                          aliases=["login", "identity", "sso"],
                          base=dict(cpu=30, mem=45, lat=90, err=0.15, rpm=3000)),
    "inventory":     dict(display="Inventory", tier=2, bu="Supply Chain", desc="Stock levels and reservations",
                          aliases=["stock", "warehouse stock"],
                          base=dict(cpu=38, mem=55, lat=140, err=0.20, rpm=900)),
    "catalog":       dict(display="Catalog", tier=2, bu="Commerce", desc="Product data, prices and images",
                          aliases=["product catalog", "pim"],
                          base=dict(cpu=35, mem=62, lat=160, err=0.15, rpm=2600)),
    "notifications": dict(display="Notifications", tier=2, bu="Platform", desc="Email, push and SMS messaging",
                          aliases=["messaging", "alerts service"],
                          base=dict(cpu=28, mem=48, lat=120, err=0.30, rpm=1500)),
    "shipping":      dict(display="Shipping", tier=2, bu="Supply Chain", desc="Rates, labels and tracking",
                          aliases=["fulfilment", "logistics"],
                          base=dict(cpu=26, mem=50, lat=260, err=0.25, rpm=700)),
    # a healthy service with no incidents and no errors, to test "nothing to report" answers
    "loyalty":       dict(display="Loyalty", tier=3, bu="Marketing", desc="Rewards points and member tiers",
                          aliases=["rewards"], team="Growth-Engineering",
                          base=dict(cpu=15, mem=40, lat=100, err=0.10, rpm=300)),
}
TEAM["loyalty"] = "Growth-Engineering"
# a decommissioned service: it exists in the CMDB but has no incidents, logs or metrics at all
DECOMMISSIONED = dict(service="legacy-reports", display="Legacy Reports", tier=3, bu="Finance", team="Finance-Systems",
                      desc="Retired reporting tool", aliases=["reports"])

# (service, depends_on, kind): checkout needs auth, payments and inventory to work at all
DEPS = [("checkout", "payments", "hard"), ("checkout", "auth", "hard"), ("checkout", "inventory", "hard"),
        ("checkout", "catalog", "soft"), ("checkout", "shipping", "soft"), ("checkout", "notifications", "soft"),
        ("payments", "auth", "hard"), ("search", "catalog", "soft"), ("shipping", "inventory", "soft"),
        ("notifications", "auth", "soft")]
