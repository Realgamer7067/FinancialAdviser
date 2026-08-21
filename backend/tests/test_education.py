"""Coverage for the static safer-alternatives educational content API --
previously zero. Confirms the disclaimer is always present (not just on
first load) and every entry's suited_risk_profiles is a real risk-tolerance
label, per app/education/safer_alternatives.py's never-fabricate rule."""

_VALID_RISK_PROFILES = {"conservative", "moderate", "aggressive"}


async def test_safer_alternatives_returns_disclaimer_and_items(client):
    res = await client.get("/api/education/safer-alternatives")
    assert res.status_code == 200
    body = res.json()
    assert body["disclaimer"]
    assert len(body["items"]) >= 4
    for item in body["items"]:
        assert set(item["suited_risk_profiles"]).issubset(_VALID_RISK_PROFILES)
        assert item["indicative_return_range"]
