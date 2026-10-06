"""Row validation and CSV parsing shared by manual and CSV imports (plan
sections 9 Phase 01, 12.1). Pure: no DB access.

Both sources reduce to a list of raw dicts; `validate_row` turns each into an
`ImportRow` or per-field errors, so preview can show every problem at once."""

import csv
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_CSV_BYTES = 1_000_000
MAX_ROWS = 2_000
SCHEMA_VERSION = "pie-import-v1"

ASSET_TYPES = {
    "listed_equity",
    "etf",
    "mutual_fund",
    "deposit",
    "gold",
    "cash",
    "other",
    "unclassified",  # only produced by legacy-snapshot adoption
}
OWNERSHIPS = {"sole", "joint", "other"}
CSV_COLUMNS = [
    "asset_type",
    "isin",
    "symbol",
    "description",
    "units",
    "value",
    "valuation_date",
    "cost_basis",
    "locked",
    "ownership",
]
_REQUIRED_COLUMNS = {"asset_type", "valuation_date"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRUE = {"true", "1", "yes"}
_FALSE = {"false", "0", "no", ""}


class CsvError(ValueError):
    """The file as a whole is unusable (size, encoding, header)."""


@dataclass(frozen=True)
class ImportRow:
    asset_type: str
    isin: str | None
    symbol: str | None
    description: str | None
    units: Decimal | None
    value: Decimal | None
    valuation_date: date
    cost_basis: Decimal | None
    locked: bool
    ownership: str
    approved_instrument_id: uuid.UUID | None = None

    @property
    def raw_identifier(self) -> str | None:
        return self.isin or self.symbol or self.description

    def dedup_key(self) -> tuple[str, str]:
        ident = (self.isin or self.symbol or self.description or "").strip().lower()
        return (self.asset_type, ident)

    def canonical(self) -> dict:
        return {
            "asset_type": self.asset_type,
            "isin": self.isin,
            "symbol": self.symbol,
            "description": self.description,
            "units": None if self.units is None else str(self.units),
            "value": None if self.value is None else str(self.value),
            "valuation_date": self.valuation_date.isoformat(),
            "cost_basis": None if self.cost_basis is None else str(self.cost_basis),
            "locked": self.locked,
            "ownership": self.ownership,
            "approved_instrument_id": None
            if self.approved_instrument_id is None
            else str(self.approved_instrument_id),
        }


@dataclass
class RowResult:
    ordinal: int
    row: ImportRow | None
    errors: list[dict] = field(default_factory=list)


def content_hash(rows: list[ImportRow]) -> str:
    payload = json.dumps([r.canonical() for r in rows], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _decimal(raw, name: str, errors: list[dict], *, positive: bool = False) -> Decimal | None:
    s = _clean(raw)
    if s is None:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        errors.append({"field": name, "message": "not a number"})
        return None
    if not d.is_finite():
        errors.append({"field": name, "message": "must be finite"})
        return None
    if d < 0 or (positive and d == 0):
        errors.append({"field": name, "message": "must be greater than zero" if positive else "must not be negative"})
        return None
    return d


def validate_row(ordinal: int, raw: dict) -> RowResult:
    errors: list[dict] = []

    asset_type = (_clean(raw.get("asset_type")) or "").lower()
    if asset_type not in ASSET_TYPES - {"unclassified"}:
        errors.append({"field": "asset_type", "message": f"must be one of {sorted(ASSET_TYPES - {'unclassified'})}"})

    isin = _clean(raw.get("isin"))
    isin = isin.upper() if isin else None
    symbol = _clean(raw.get("symbol"))
    description = _clean(raw.get("description"))
    if not (isin or symbol or description):
        errors.append({"field": "isin", "message": "one of isin, symbol or description is required"})

    units = _decimal(raw.get("units"), "units", errors, positive=True)
    value = _decimal(raw.get("value"), "value", errors)
    cost_basis = _decimal(raw.get("cost_basis"), "cost_basis", errors)
    if units is None and value is None and not any(e["field"] in ("units", "value") for e in errors):
        errors.append({"field": "units", "message": "units or value is required"})

    date_s = _clean(raw.get("valuation_date"))
    valuation_date = None
    if date_s is None:
        errors.append({"field": "valuation_date", "message": "required (YYYY-MM-DD)"})
    elif not _DATE_RE.match(date_s):
        errors.append({"field": "valuation_date", "message": "must be YYYY-MM-DD"})
    else:
        try:
            valuation_date = date.fromisoformat(date_s)
        except ValueError:
            errors.append({"field": "valuation_date", "message": "not a real date"})

    locked_raw = raw.get("locked")
    if isinstance(locked_raw, bool):
        locked = locked_raw
    else:
        ls = (_clean(locked_raw) or "").lower()
        if ls not in _TRUE | _FALSE:
            errors.append({"field": "locked", "message": "must be true or false"})
        locked = ls in _TRUE

    ownership = (_clean(raw.get("ownership")) or "sole").lower()
    if ownership not in OWNERSHIPS:
        errors.append({"field": "ownership", "message": f"must be one of {sorted(OWNERSHIPS)}"})

    approved = None
    approved_raw = _clean(raw.get("instrument_id"))
    if approved_raw:
        try:
            approved = uuid.UUID(approved_raw)
        except ValueError:
            errors.append({"field": "instrument_id", "message": "not a valid id"})

    if errors:
        return RowResult(ordinal, None, errors)
    return RowResult(
        ordinal,
        ImportRow(
            asset_type=asset_type,
            isin=isin,
            symbol=symbol,
            description=description,
            units=units,
            value=value,
            valuation_date=valuation_date,  # type: ignore[arg-type]
            cost_basis=cost_basis,
            locked=locked,
            ownership=ownership,
            approved_instrument_id=approved,
        ),
    )


def validate_rows(raw_rows: list[dict]) -> list[RowResult]:
    if len(raw_rows) > MAX_ROWS:
        raise CsvError(f"too many rows (max {MAX_ROWS})")
    return [validate_row(i + 1, raw) for i, raw in enumerate(raw_rows)]


def parse_csv(data: bytes) -> list[dict]:
    if len(data) > MAX_CSV_BYTES:
        raise CsvError(f"file too large (max {MAX_CSV_BYTES} bytes)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvError("file must be UTF-8 text")
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        raise CsvError("file is empty")
    if len(set(header)) != len(header):
        raise CsvError("duplicate column names in header")
    unknown = [h for h in header if h not in CSV_COLUMNS]
    if unknown:
        raise CsvError(f"unknown columns: {unknown}; expected a subset of {CSV_COLUMNS}")
    missing = _REQUIRED_COLUMNS - set(header)
    if missing:
        raise CsvError(f"missing required columns: {sorted(missing)}")
    rows: list[dict] = []
    for line in reader:
        if not any(cell.strip() for cell in line):
            continue
        if len(line) > len(header):
            raise CsvError(f"row {len(rows) + 1} has more cells than the header")
        rows.append(dict(zip(header, line)))
        if len(rows) > MAX_ROWS:
            raise CsvError(f"too many rows (max {MAX_ROWS})")
    return rows
