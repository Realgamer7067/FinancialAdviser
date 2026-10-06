"""Phase 00: private-mode guards (cross-site write rejection, CORS gating)."""


async def test_cross_site_write_to_v4_rejected(client):
    r = await client.post("/api/v4/anything", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


async def test_foreign_origin_write_to_v4_rejected(client):
    r = await client.post("/api/v4/anything", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


async def test_same_origin_write_to_v4_passes_guard(client):
    # No such route yet -> 404, i.e. the guard let it through.
    r = await client.post(
        "/api/v4/anything",
        headers={"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code == 404


async def test_non_browser_write_passes_guard(client):
    r = await client.post("/api/v4/anything")
    assert r.status_code == 404


async def test_reads_not_guarded(client):
    r = await client.get("/api/v4/anything", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 404


async def test_github_dev_origin_not_allowed_by_default(client):
    r = await client.get("/health", headers={"Origin": "https://x-3000.app.github.dev"})
    assert "access-control-allow-origin" not in r.headers
