"""Read-only, bounded analytics over the committed battery-return Gold snapshot."""

import datetime as dt
import json
import pathlib
import threading
import time
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
from fabric_api import kql

FIELDS = {
    "return_id", "battery_serial", "product_id", "batch_id", "shipment_id",
    "originator_type", "originator_id", "submitted_by_type", "submitted_by_id",
    "receiving_warehouse_id", "country", "reported_reason", "inspection_finding",
    "return_status", "product_name", "battery_technology", "factory_id",
    "distributor_id", "retailer_id", "warranty_status", "resolution_action",
}
GROUPS = FIELDS | {"return_month", "return_year"}
METRICS = {
    "ReturnCases", "DistinctBatteries", "UnknownOrigins", "ClosedCases",
    "InWarrantyCases", "AvgClosedTurnaroundDays",
}
AGGREGATES = (
    "ReturnCases=count(), DistinctBatteries=count_distinct(battery_serial), "
    "UnknownOrigins=countif(originator_type == 'Unknown' or isempty(originator_id)), "
    "ClosedCases=countif(return_status == 'Closed'), "
    "InWarrantyCases=countif(warranty_status == 'InWarranty'), "
    "AvgClosedTurnaroundDays=round(avgif((event_time-return_registered_at)/1d, "
    "return_status == 'Closed'), 2)"
)
DETAIL_COLUMNS = (
    "return_id, battery_serial, product_id, product_name, batch_id, shipment_id, country,"
    " originator_type, originator_id, submitted_by_type, submitted_by_id,"
    " receiving_warehouse_id, reported_reason, inspection_finding, return_status,"
    " revision, return_registered_at, event_time, warranty_status, warranty_expires_at,"
    " resolution_action, factory_id, distributor_id, retailer_id"
)
_lock = threading.RLock()
_snapshot = None
_snapshot_at = 0


class InvalidQuestion(ValueError):
    pass


def snapshot():
    global _snapshot, _snapshot_at
    with _lock:
        if _snapshot is None or time.monotonic() - _snapshot_at > 30:
            rows = kql(
                "ReturnsGoldCommits | where data_label == 'SYNTHETIC'"
                " | top 1 by published_at desc"
            )
            if not rows:
                raise RuntimeError("No validated Gold publication is available.")
            _snapshot = rows[0]
            _snapshot_at = time.monotonic()
        return dict(_snapshot)


def literal(value):
    if not isinstance(value, str) or len(value) > 250:
        raise InvalidQuestion("Filter values must be strings of at most 250 characters.")
    return json.dumps(value, ensure_ascii=True)


def date_value(value):
    if not isinstance(value, str) or len(value) != 10:
        raise InvalidQuestion("Dates must use YYYY-MM-DD.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise InvalidQuestion("Invalid calendar date.") from None


def filter_query(filters=None, date_from=None, date_to=None, publication=None):
    publication = publication or snapshot()
    query = "ReturnsGoldRaw | where publish_id == " + literal(publication["publish_id"])
    query += "\n| extend return_month=format_datetime(return_registered_at, 'yyyy-MM'), return_year=format_datetime(return_registered_at, 'yyyy')"
    if filters is None:
        filters = []
    if not isinstance(filters, list) or len(filters) > 10:
        raise InvalidQuestion("Use at most ten structured filters.")
    for entry in filters:
        if not isinstance(entry, dict) or set(entry) != {"field", "op", "value"}:
            raise InvalidQuestion("Each filter requires field, op, and value.")
        field, operator, value = entry["field"], entry["op"], entry["value"]
        if not isinstance(field, str) or not isinstance(operator, str):
            raise InvalidQuestion("Filter field and operator must be strings.")
        if field not in GROUPS:
            raise InvalidQuestion("Unsupported filter field.")
        operators = {"eq": "=~", "neq": "!~", "contains": "contains", "not_contains": "!contains"}
        if operator not in operators:
            raise InvalidQuestion("Unsupported filter operator.")
        query += f"\n| where {field} {operators[operator]} {literal(value)}"
    start = date_value(date_from) if date_from else None
    end = date_value(date_to) if date_to else None
    if start and end and start > end:
        raise InvalidQuestion("Start date must not follow end date.")
    if start:
        query += f"\n| where return_registered_at >= datetime({start.isoformat()}T00:00:00Z)"
    if end:
        try:
            exclusive = end + dt.timedelta(days=1)
        except OverflowError:
            raise InvalidQuestion("End date is outside the supported range.") from None
        query += f"\n| where return_registered_at < datetime({exclusive.isoformat()}T00:00:00Z)"
    return query


def analytics(kind="summary", group_by=None, filters=None, date_from=None, date_to=None,
              limit=20, sort_by=None, direction=None):
    if kind not in {"summary", "grouped", "trend"}:
        raise InvalidQuestion("Choose summary, grouped, or trend.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidQuestion("Limit must be an integer from 1 to 100.")
    publication = snapshot()
    base = filter_query(filters, date_from, date_to, publication)
    if kind == "summary":
        query = base + "\n| summarize " + AGGREGATES + (
            ", FirstReturn=min(return_registered_at), LastReturn=max(return_registered_at),"
            " Batches=count_distinct(batch_id), Countries=count_distinct(country)"
            "\n| extend UnknownOriginPct=round(100.0 * UnknownOrigins / ReturnCases, 2),"
            " InWarrantyPct=round(100.0 * InWarrantyCases / ReturnCases, 2)"
        )
    else:
        groups = group_by or (["return_month"] if kind == "trend" else [])
        if (
            not isinstance(groups, list) or not 1 <= len(groups) <= 3
            or any(not isinstance(field, str) for field in groups) or len(set(groups)) != len(groups)
        ):
            raise InvalidQuestion("Choose one to three distinct grouping fields.")
        if any(field not in GROUPS for field in groups):
            raise InvalidQuestion("Unsupported grouping field.")
        sort_by = sort_by or ("return_month" if kind == "trend" else "ReturnCases")
        direction = direction or ("asc" if kind == "trend" else "desc")
        if sort_by not in METRICS | set(groups) or direction not in {"asc", "desc"}:
            raise InvalidQuestion("Unsupported sorting.")
        query = (
            "let Matching = " + base + ";\n"
            "let MatchingCount = toscalar(Matching | count);\n"
            "Matching | summarize " + AGGREGATES + " by " + ", ".join(groups)
            + "\n| extend ShareOfMatchingCases=round(100.0 * ReturnCases / MatchingCount, 2)"
            + f"\n| order by {sort_by} {direction}\n| take {limit}"
        )
    rows = kql(query)
    return {
        "source": "Validated Gold return cases", "publish_id": publication["publish_id"],
        "data_label": "SYNTHETIC", "query": query, "rows": rows,
        "filters": filters or [], "date_from": date_from, "date_to": date_to,
        "notes": "Counts are return cases, not defect/return rates against total units sold. Days are elapsed calendar days for closed cases.",
    }


def case_records(filters=None, date_from=None, date_to=None, limit=20):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise InvalidQuestion("Case limit must be an integer from 1 to 50.")
    publication = snapshot()
    query = (
        filter_query(filters, date_from, date_to, publication)
        + "\n| order by return_registered_at desc, return_id desc"
        + "\n| project " + DETAIL_COLUMNS + f"\n| take {limit}"
    )
    return {
        "source": "Validated Gold case traceability", "publish_id": publication["publish_id"],
        "data_label": "SYNTHETIC", "query": query, "rows": kql(query),
        "notes": "One latest revision per return case. A battery can have more than one legitimate return case.",
    }


def lineage():
    publication = snapshot()
    expected = json.loads((ROOT.parent / "config" / "expected.json").read_text())
    return {
        "source": "Committed pipeline lineage", "data_label": "SYNTHETIC",
        "publication": publication, "input_files": list(expected["source_files"]),
        "pipeline_name": "BatteryReturns_Bronze_Silver_Gold",
        "flow": ["Four input files", "Bronze", "Silver and quarantine", "Gold", "Eventhouse", "Dashboard"],
        "notes": [
            "Three intentionally invalid test events are quarantined.",
            "Replay duplicates are not new return cases; valid lifecycle revisions are retained.",
            "The pipeline rebuilds a fixed synthetic source snapshot; rerunning does not invent new cases.",
            "Teams alerts use a separate live Eventstream, not this historical Gold snapshot.",
        ],
    }


def dictionary():
    return {
        "data_label": "SYNTHETIC", "source": "Battery Returns data dictionary",
        "publication": snapshot(), "filter_and_group_fields": sorted(GROUPS),
        "metrics": sorted(METRICS),
        "definitions": {
            "originator_type / originator_id": "Original party who initiated the return; Unknown is valid missing provenance.",
            "submitted_by_type / submitted_by_id": "Party who submitted the return; may differ from the original initiator.",
            "reported_reason": "Customer/channel complaint, not a proven technical cause.",
            "inspection_finding": "Recorded synthetic inspection finding; never infer a causal explanation beyond the stored result.",
            "revision": "Highest valid business lifecycle revision wins, not the last message arrival.",
            "return_registered_at": "Original registration timestamp. Dashboard date filters apply here, in UTC.",
            "event_time": "Timestamp of the latest case lifecycle event, not necessarily the registration date.",
            "warranty_status": "Calculated by comparing registration against invoice date plus product warranty months.",
            "ReturnCases": "One latest row per return ID; not one per battery or per lifecycle message.",
            "AvgClosedTurnaroundDays": "Mean elapsed calendar days from registration to closure, only for closed cases.",
        },
        "limitations": [
            "All identifiers, outcomes, and distributions are fabricated demonstration data.",
            "No total population of batteries sold/shipped is supplied; defect rates cannot be calculated.",
            "No repair costs, sales revenue, customer names/contact details, or validated causal model are supplied.",
            "The chat query tools expose current Gold case snapshots, not full lifecycle event history.",
        ],
    }


def dashboard_data(filters=None, date_from=None, date_to=None):
    common = {"filters": filters, "date_from": date_from, "date_to": date_to}
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": analytics(**common)["rows"][0],
        "initiators": analytics("grouped", ["originator_type"], **common)["rows"],
        "reasons": analytics("grouped", ["reported_reason"], **common)["rows"],
        "findings": analytics("grouped", ["inspection_finding"], **common)["rows"],
        "batches": analytics("grouped", ["batch_id", "product_id"], limit=30, **common)["rows"],
        "trend": analytics(
            "trend", ["return_month"], sort_by="return_month", direction="asc", limit=100, **common
        )["rows"],
        "cases": case_records(limit=30, **common)["rows"],
        "lineage": lineage(),
    }
