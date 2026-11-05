"""Paste into a Fabric Python/PySpark notebook cell; running it sends nothing.

Install azure-eventhub in a separate notebook cell before sending live events.
Start with send_phase("baseline") for a dry run.
"""

import copy
import getpass
import json
import time
import uuid
import warnings
from datetime import datetime, timezone


RUN_ID = "demo-" + uuid.uuid4().hex[:8]
PHASES = ("baseline", "trigger", "more", "replay_and_inspect")
_phase_cache = {}
_registrations = {}


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _registration(case_number):
    definitions = {
        1: ("CONTROL-A", "EndUser", "USER-001", "Retailer", "SHOP-001",
            "Transit damage", "Country-A"),
        2: ("CONTROL-A", "Warehouse", "WH-001", "Warehouse", "WH-001",
            "Incorrect product", "Country-B"),
        3: ("CONTROL-B", "Unknown", "", "Distributor", "DIST-001",
            "Not provided", "Country-C"),
        4: ("SPIKE-A", "Retailer", "SHOP-002", "Distributor", "DIST-002",
            "Not charging", "Country-A"),
        5: ("SPIKE-A", "EndUser", "USER-002", "Retailer", "SHOP-003",
            "Not charging", "Country-B"),
        6: ("SPIKE-A", "Retailer", "SHOP-004", "Retailer", "SHOP-004",
            "Not charging", "Country-C"),
        7: ("SPIKE-A", "Distributor", "DIST-003", "Warehouse", "WH-002",
            "Not charging", "Country-A"),
        8: ("SPIKE-A", "Warehouse", "WH-003", "Warehouse", "WH-003",
            "Not charging", "Country-B"),
    }
    batch, role, origin, submit_role, submit_id, reason, country = definitions[case_number]
    timestamp = _utc_now()
    return {
        "data_label": "SYNTHETIC",
        "demo_run_id": RUN_ID,
        "event_id": f"{RUN_ID}-EVT-{case_number:03d}-R1",
        "event_time": timestamp,
        "event_type": "ReturnRegistered",
        "revision": 1,
        "return_id": f"{RUN_ID}-RET-{case_number:03d}",
        "return_registered_at": timestamp,
        "battery_serial": f"{RUN_ID}-BAT-{case_number:03d}",
        "product_id": "BAT-MODEL-01",
        "batch_id": batch,
        "shipment_id": f"SHIP-{case_number:03d}",
        "originator_type": role,
        "originator_id": origin,
        "submitted_by_type": submit_role,
        "submitted_by_id": submit_id,
        "receiving_warehouse_id": "RETURNS-HUB-01",
        "country": country,
        "reported_reason": reason,
        "inspection_finding": "Pending",
        "return_status": "Requested",
    }


def build_phase(phase):
    """Create stable snapshots; rerunning a phase replays the same event IDs."""
    if phase not in PHASES:
        raise ValueError(f"Choose one of: {', '.join(PHASES)}")
    if phase in _phase_cache:
        return copy.deepcopy(_phase_cache[phase])
    index = PHASES.index(phase)
    if index and PHASES[index - 1] not in _phase_cache:
        raise ValueError(f"Build or send {PHASES[index - 1]} first.")
    if phase == "replay_and_inspect":
        replay = copy.deepcopy(_registrations[4])
        inspected = copy.deepcopy(_registrations[4])
        inspected.update({
            "event_id": f"{RUN_ID}-EVT-004-R2",
            "event_time": _utc_now(),
            "event_type": "InspectionCompleted",
            "revision": 2,
            "inspection_finding": "No fault found",
            "return_status": "Inspected",
        })
        events = [replay, inspected]
    else:
        case_numbers = {
            "baseline": (1, 2, 3, 4, 5),
            "trigger": (6,),
            "more": (7, 8),
        }[phase]
        events = [_registration(number) for number in case_numbers]
        _registrations.update(zip(case_numbers, copy.deepcopy(events)))
    _phase_cache[phase] = copy.deepcopy(events)
    return copy.deepcopy(events)


def send_phase(phase, live=False, delay_seconds=2):
    """Dry run by default; live sending prompts for credentials without echo."""
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative.")
    events = build_phase(phase)
    if not live:
        for event in events:
            print(json.dumps(event))
        print(f"DRY RUN ONLY: {len(events)} events, run={RUN_ID}, phase={phase}")
        return events

    try:
        from azure.eventhub import EventData, EventHubProducerClient, TransportType
        from websocket import (
            create_connection,
            WebSocketAddressException,
            WebSocketTimeoutException,
            WebSocketConnectionClosedException,
        )
    except ImportError:
        raise RuntimeError(
            "Install the Event Hubs and WebSocket dependencies in a separate cell: "
            "%pip install azure-eventhub websocket-client"
        ) from None

    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            connection_string = getpass.getpass(
                "Paste the Eventstream custom endpoint Event Hub connection string (hidden): "
            ).strip()
        except getpass.GetPassWarning:
            raise RuntimeError(
                "Hidden input is unavailable. Use the organizer-approved secret "
                "retrieval method; do not enter credentials into visible input."
            ) from None
    if not connection_string:
        raise ValueError("A connection string is required; nothing was sent.")
    if "entitypath=" in connection_string.lower():
        eventhub_name = None
    else:
        eventhub_name = input("Event Hub name from the SAME custom endpoint: ").strip()
        if not eventhub_name:
            raise ValueError("An Event Hub name is required; nothing was sent.")

    try:
        producer = EventHubProducerClient.from_connection_string(
            conn_str=connection_string,
            eventhub_name=eventhub_name,
            transport_type=TransportType.AmqpOverWebsocket,
        )
        with producer:
            for event in events:
                batch = producer.create_batch()
                batch.add(EventData(json.dumps(event)))
                producer.send_batch(batch)
                print(
                    f"SENT run={RUN_ID} phase={phase} "
                    f"event={event['event_id']} batch={event['batch_id']}"
                )
                if delay_seconds:
                    time.sleep(delay_seconds)
    except Exception as error:
        # SDK messages can include connection details; keep notebook output safe.
        raise RuntimeError(
            f"Send did not complete ({type(error).__name__}). Check endpoint, "
            "permissions and permitted network access. Rerun the same phase to "
            "replay stable IDs; verify ingestion before moving on."
        ) from None
    finally:
        connection_string = None
    return events


print(f"Simulator ready. Run ID: {RUN_ID}. No events sent.")
print("Phases: baseline -> trigger -> more -> replay_and_inspect")
print("Dry run: send_phase('baseline')")
print("Live: send_phase('baseline', live=True)")
