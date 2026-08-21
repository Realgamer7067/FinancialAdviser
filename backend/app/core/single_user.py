"""Single-user mode: this is a college-project demo, not a deployed multi-tenant
app, so there is no login/signup -- every request acts as one fixed seeded User
row. See `app.main`'s startup hook for where this row gets created."""

from uuid import UUID

SINGLE_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
