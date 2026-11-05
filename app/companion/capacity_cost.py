"""Transparent capacity-only PAYG projections from the public Azure retail API."""

import datetime as dt
import decimal
import json
import pathlib
import threading
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).parent
REGION = "westcentralus"
SKUS = ["F2", "F4", "F8", "F16", "F32", "F64", "F128", "F256", "F512"]
_lock = threading.RLock()
_cache = {}


def load_prices(currency="USD"):
    if currency not in {"USD", "INR"}:
        raise ValueError("Choose USD or INR.")
    with _lock:
        if currency in _cache:
            age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(_cache[currency]["retrieved_at"])
            if age >= dt.timedelta(hours=24):
                del _cache[currency]
        if currency not in _cache:
            path = ROOT / f"retail-prices-{currency}.json"
            if path.exists():
                stored = json.loads(path.read_text())
                age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(stored["retrieved_at"])
                if age < dt.timedelta(hours=24) and stored["region"] == REGION:
                    _cache[currency] = stored
        if currency in _cache:
            return _cache[currency]
        query = {
            "api-version": "2023-01-01-preview", "currencyCode": currency,
            "$filter": (
                "serviceName eq 'Microsoft Fabric' and "
                f"armRegionName eq '{REGION}' and priceType eq 'Consumption'"
            ),
        }
        source_url = "https://prices.azure.com/api/retail/prices?" + urllib.parse.urlencode(query)
        url = source_url
        rows = []
        for _ in range(10):
            if urllib.parse.urlparse(url).hostname != "prices.azure.com":
                raise RuntimeError("Unexpected retail pricing host.")
            with urllib.request.urlopen(url, timeout=60) as response:
                page = json.load(response)
            rows.extend(page["Items"])
            url = page.get("NextPageLink")
            if not url:
                break
        if url:
            raise RuntimeError("Retail pricing pagination exceeded the bounded limit.")
        stored = {
            "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "region": REGION, "source_url": source_url, "items": rows,
        }
        (ROOT / f"retail-prices-{currency}.json").write_text(json.dumps(stored, indent=2))
        _cache[currency] = stored
        return stored


def base_rate(rows, currency):
    candidates = [
        row for row in rows
        if row.get("productName") == "Fabric Capacity"
        and row.get("meterName") == "Compute Pool Capacity Usage CU"
        and row.get("type") == "Consumption"
        and row.get("unitOfMeasure") == "1 Hour"
        and row.get("armRegionName") == REGION
        and row.get("currencyCode") == currency
        and row.get("isPrimaryMeterRegion") is True
        and not row.get("reservationTerm")
    ]
    if not candidates:
        raise RuntimeError("The region's authoritative base capacity meter is unavailable; no price was assumed.")
    current = max(candidates, key=lambda row: row["effectiveStartDate"])
    if decimal.Decimal(str(current["retailPrice"])) <= 0:
        raise RuntimeError("The base capacity rate is invalid.")
    return current


def estimate(sku="F2", hours_per_day=24, currency="USD"):
    if sku not in SKUS:
        raise ValueError("Choose a supported Fabric capacity SKU.")
    if type(hours_per_day) not in {int, float} or not 0 <= hours_per_day <= 24:
        raise ValueError("Charged hours per day must be between 0 and 24.")
    prices = load_prices(currency)
    meter = base_rate(prices["items"], currency)
    rate = decimal.Decimal(str(meter["retailPrice"]))
    units = int(sku[1:])
    hourly = rate * units
    hours = decimal.Decimal(str(hours_per_day))
    amounts = {
        key: float((hourly * hours * days).quantize(decimal.Decimal(".01"), rounding=decimal.ROUND_HALF_UP))
        for key, days in (("day", 1), ("week", 7), ("month", 30), ("year", 365))
    }
    return {
        "kind": "Capacity-only pay-as-you-go estimate, not an invoice",
        "current_workspace": "FT1 trial; these are hypothetical paid-capacity prices",
        "sku": sku, "capacity_units": units, "currency": currency,
        "region": REGION, "region_label": "West Central US",
        "hours_per_day": hours_per_day,
        "per_cu_hour": float(rate), "capacity_hourly_rate": float(hourly),
        "amounts": amounts, "period_days": {"day": 1, "week": 7, "month": 30, "year": 365},
        "retrieved_at": prices["retrieved_at"], "meter_name": meter["meterName"],
        "meter_id": meter["meterId"], "effective_start_date": meter["effectiveStartDate"],
        "price_source": "Azure Retail Prices API",
        "pricing_page": "https://azure.microsoft.com/en-us/pricing/details/microsoft-fabric/",
        "assumptions": [
            "Whole-capacity cost; not a measured per-workspace allocation or account invoice.",
            "One month means 30 days; one year means 365 days. The yearly figure is PAYG, not a reservation quote.",
            "Charged hours mean capacity provisioned hours, not notebook execution hours. Savings require actual pausing.",
            "Excludes OneLake storage/transactions, bandwidth, licenses, taxes, overage, and optional on-demand services.",
            "Regional public retail list prices are not negotiated subscription prices.",
            "The selected SKU is a pricing scenario, not a validated performance-sizing recommendation.",
        ],
    }
