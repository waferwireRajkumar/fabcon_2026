import datetime as dt
import http.client
import http.server
import json
import pathlib
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import capacity_cost
import chat_engine
import gold_data
import server


class GoldTests(unittest.TestCase):
    @patch.object(gold_data, "snapshot", return_value={"publish_id": "verified-snapshot"})
    def test_lineage_reads_packaged_input_contract(self, _snapshot):
        result = gold_data.lineage()
        self.assertEqual(
            set(result["input_files"]),
            {"products.csv", "batteries.csv", "shipments.csv", "return_events.json"},
        )
        self.assertEqual(result["publication"]["publish_id"], "verified-snapshot")

    def test_literal_and_inclusive_utc_dates(self):
        value = 'India" | take 999999\n; .drop table ReturnsGoldRaw'
        query = gold_data.filter_query(
            [{"field": "country", "op": "eq", "value": value}],
            "2024-02-29", "2024-02-29", {"publish_id": "verified-snapshot"},
        )
        self.assertIn("country =~ " + json.dumps(value), query)
        self.assertIn(">= datetime(2024-02-29T00:00:00Z)", query)
        self.assertIn("< datetime(2024-03-01T00:00:00Z)", query)
        self.assertNotIn("\n; .drop", query)

    @patch.object(gold_data, "snapshot", return_value={"publish_id": "verified-snapshot"})
    @patch.object(gold_data, "kql", return_value=[])
    def test_unknown_fields_and_bad_filter_types_do_not_execute(self, execute, _snapshot):
        for filters in [
            [{"field": "country | take 5000", "op": "eq", "value": "India"}],
            [{"field": ["country"], "op": "eq", "value": "India"}],
            [{"field": "country", "op": ["eq"], "value": "India"}],
            [{"field": "country", "op": "eq", "value": {"bad": "value"}}],
            [{"field": "country", "op": "eq", "value": "India", "extra": "bad"}],
            {"country": "India"},
        ]:
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                gold_data.analytics(filters=filters)
        execute.assert_not_called()

    @patch.object(gold_data, "snapshot", return_value={"publish_id": "verified-snapshot"})
    @patch.object(gold_data, "kql", return_value=[])
    def test_trends_are_chronological_and_rankings_are_bounded(self, execute, _snapshot):
        gold_data.analytics(kind="trend")
        self.assertIn("order by return_month asc", execute.call_args.args[0])
        gold_data.analytics(kind="grouped", group_by=["batch_id"], limit=5)
        self.assertIn("order by ReturnCases desc\n| take 5", execute.call_args.args[0])
        for groups in [["batch_id", "batch_id"], [["batch_id"]], ["unsupported"]]:
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                gold_data.analytics(kind="grouped", group_by=groups)

    @patch.object(gold_data, "snapshot", return_value={"publish_id": "verified-snapshot"})
    @patch.object(gold_data, "kql", return_value=[])
    def test_bad_dates_and_excessive_limits_are_rejected(self, execute, _snapshot):
        for dates in [("2026-02-30", None), ("2026-11-04", "2026-11-03"), (None, "9999-12-31")]:
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                gold_data.analytics(date_from=dates[0], date_to=dates[1])
        for limit in [True, 0, 101, "5"]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                gold_data.analytics(limit=limit)
        with self.assertRaises(ValueError):
            gold_data.case_records(limit=51)
        execute.assert_not_called()


class CostTests(unittest.TestCase):
    def setUp(self):
        self.meter = {
            "productName": "Fabric Capacity", "meterName": "Compute Pool Capacity Usage CU",
            "type": "Consumption", "unitOfMeasure": "1 Hour", "armRegionName": capacity_cost.REGION,
            "currencyCode": "USD", "isPrimaryMeterRegion": True, "retailPrice": 0.2,
            "effectiveStartDate": "2026-01-01T00:00:00Z", "meterId": "base-meter",
        }
        self.prices = {"items": [self.meter], "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    def test_base_meter_excludes_storage_overage_and_reservations(self):
        irrelevant = [
            {**self.meter, "meterName": "Capacity Overage CU", "retailPrice": 0.6},
            {**self.meter, "productName": "OneLake", "retailPrice": 0.023},
            {**self.meter, "type": "Reservation", "reservationTerm": "1 Year"},
            {**self.meter, "currencyCode": "INR"},
            {**self.meter, "armRegionName": "eastus"},
            {**self.meter, "isPrimaryMeterRegion": False},
        ]
        self.assertEqual(capacity_cost.base_rate(irrelevant + [self.meter], "USD"), self.meter)
        with self.assertRaises(RuntimeError):
            capacity_cost.base_rate(irrelevant, "USD")

    def test_exact_period_arithmetic_and_paused_hours(self):
        with patch.object(capacity_cost, "load_prices", return_value=self.prices):
            self.assertEqual(
                capacity_cost.estimate()["amounts"],
                {"day": 9.6, "week": 67.2, "month": 288.0, "year": 3504.0},
            )
            eight_hours = capacity_cost.estimate("F4", 8)
            self.assertEqual(eight_hours["amounts"]["day"], 6.4)
            self.assertEqual(eight_hours["amounts"]["month"], 192)
            self.assertEqual(capacity_cost.estimate(hours_per_day=0)["amounts"]["year"], 0)
            self.assertEqual(capacity_cost.estimate(hours_per_day=0.0625)["amounts"]["day"], 0.03)
        for hours in [-1, 25, True, float("nan"), float("inf")]:
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                capacity_cost.estimate(hours_per_day=hours)

    def test_in_memory_pricing_expires(self):
        expired = {**self.prices, "retrieved_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()}
        fresh = {**self.prices, "region": capacity_cost.REGION}
        with patch.dict(capacity_cost._cache, {"USD": expired}, clear=True), \
                patch.object(pathlib.Path, "exists", return_value=True), \
                patch.object(pathlib.Path, "read_text", return_value=json.dumps(fresh)):
            self.assertEqual(capacity_cost.load_prices()["retrieved_at"], fresh["retrieved_at"])


class PermissionTests(unittest.TestCase):
    def test_only_named_read_only_tools_are_allowed_once(self):
        for name in chat_engine.TOOLS:
            decision = chat_engine.permission(
                types.SimpleNamespace(kind="custom-tool", tool_name=name, managed_approval_required=False), None,
            )
            self.assertIsInstance(decision, chat_engine.PermissionDecisionApproveOnce)
        for kind, name, managed in [
            ("shell", "gold_analytics", False),
            ("custom-tool", "arbitrary_tool", False),
            ("custom-tool", "gold_analytics", True),
            ("write", "gold_case_records", False),
        ]:
            decision = chat_engine.permission(
                types.SimpleNamespace(kind=kind, tool_name=name, managed_approval_required=managed), None,
            )
            self.assertIsInstance(decision, chat_engine.PermissionDecisionReject)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.http.server_address[1]
        cls.origin = f"http://localhost:{cls.port}"
        cls.settings = patch.multiple(server, PORT=cls.port, ORIGIN=cls.origin)
        cls.settings.start()
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.settings.stop()

    def call(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_nonlocal_host_and_foreign_origin_are_rejected(self):
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": "outside.example"})[0], 403)
        self.assertEqual(self.call("POST", "/api/chat", "{}", {
            "Origin": "https://outside.example", "X-CSRF-Token": server.CSRF,
        })[0], 403)
        self.assertEqual(self.call("GET", "/../server.py")[0], 404)

    def test_malformed_chat_requests_fail_cleanly(self):
        headers = {
            "Origin": self.origin, "X-CSRF-Token": server.CSRF, "Content-Type": "application/json",
            "Cookie": "battery_demo=00000000-0000-4000-8000-000000000001",
        }
        for body in [[], None, {"message": "Hello"}, {"message": 42}, {"unexpected": True}]:
            with self.subTest(body=body):
                self.assertEqual(self.call("POST", "/api/chat", json.dumps(body), headers)[0], 400)

    def test_invalid_dashboard_filters_do_not_query_data(self):
        with patch.object(server, "dashboard") as dashboard:
            for path in [
                "/api/dashboard?date_from=2026-02-30",
                "/api/dashboard?date_from=2026-11-04&date_to=2026-11-03",
                "/api/dashboard?country=India&country=US",
                "/api/dashboard?arbitrary=1",
            ]:
                with self.subTest(path=path):
                    self.assertEqual(self.call("GET", path)[0], 400)
            dashboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
