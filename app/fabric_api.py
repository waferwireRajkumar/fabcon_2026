"""Scoped Fabric/KQL REST access using the existing Azure CLI login."""

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


WORKSPACE_ID = "0660f2dc-333d-445c-8c62-6d15515f7206"
DATABASE_ID = "c688ad4f-786d-46a3-a0b7-400177d2871f"
CLUSTER = "https://trd-x6s8dxpyykghc2cybq.z6.kusto.fabric.microsoft.com"
_tokens = {}
_token_expires = {}


def _token(resource):
    if resource not in _tokens or time.time() >= _token_expires.get(resource, 0) - 120:
        result = subprocess.run(
            [
                shutil.which("az"), "account", "get-access-token",
                "--resource", resource, "--only-show-errors", "--output", "json",
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Azure CLI could not obtain a token for {resource}")
        details = json.loads(result.stdout)
        _tokens[resource] = details["accessToken"]
        _token_expires[resource] = float(details.get("expires_on", time.time() + 2700))
    return _tokens[resource]


def request(method, url, resource, body=None):
    allowed_hosts = {
        "api.fabric.microsoft.com",
        urllib.parse.urlparse(CLUSTER).hostname,
    }
    if urllib.parse.urlparse(url).hostname not in allowed_hosts:
        raise ValueError("Refusing to send credentials to an unexpected host.")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": "Bearer " + _token(resource),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read()
            return (
                response.status,
                dict(response.headers),
                json.loads(raw) if raw else None,
            )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail[:1800]}") from None


def fabric(method, path, body=None):
    url = "https://api.fabric.microsoft.com/v1/" + path.lstrip("/")
    status, headers, result = request(
        method, url, "https://api.fabric.microsoft.com", body
    )
    if status != 202:
        return result
    location = next(
        (value for key, value in headers.items() if key.lower() == "location"), None
    )
    operation_id = next(
        (value for key, value in headers.items() if key.lower() == "x-ms-operation-id"), None
    )
    if operation_id:
        location = (
            "https://api.fabric.microsoft.com/v1/operations/"
            + urllib.parse.quote(operation_id, safe="")
        )
    if not location:
        raise RuntimeError("Async Fabric response did not include Location.")
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        delay = next(
            (value for key, value in headers.items() if key.lower() == "retry-after"),
            "2",
        )
        time.sleep(max(int(delay), 0))
        _, headers, operation = request(
            "GET", location, "https://api.fabric.microsoft.com"
        )
        if operation and operation.get("status") in ("Failed", "Cancelled"):
            raise RuntimeError(f"Fabric operation failed: {operation.get('error')}")
        if operation and operation.get("status") == "Succeeded":
            _, _, result = request(
                "GET", location.rstrip("/") + "/result",
                "https://api.fabric.microsoft.com",
            )
            return result
    raise TimeoutError("Fabric operation is still pending after four minutes.")


def kql(query, management=False):
    endpoint = "mgmt" if management else "query"
    _, _, result = request(
        "POST", CLUSTER + "/v1/rest/" + endpoint,
        "https://kusto.kusto.windows.net",
        {"db": DATABASE_ID, "csl": query},
    )
    table = result["Tables"][0]
    columns = [column["ColumnName"] for column in table["Columns"]]
    return [dict(zip(columns, row)) for row in table["Rows"]]
