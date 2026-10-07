# SPDX-License-Identifier: Apache-2.0
"""Offline proxy regressions: request credentials never become receipt identity.

Only inert header strings are used. Upstream, hardware, carbon, signing, and
receipt storage are mocked. The real HTTP routes, receipt body construction,
hash chain, and JSONL serializer run; no receipt is signed or written to disk.
"""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch


# Load just the reviewed proxy package. This keeps the focused regression
# independent of optional parent-package GPU and signing integrations.
_PACKAGE = "_szl_requester_privacy_test"
_ROOT = Path(__file__).resolve().parents[1] / "szl_energy_attest" / "meter_proxy"
_SPEC = importlib.util.spec_from_file_location(
    _PACKAGE, _ROOT / "__init__.py", submodule_search_locations=[str(_ROOT)]
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_PACKAGE] = _MODULE
_SPEC.loader.exec_module(_MODULE)
proxy = importlib.import_module(_PACKAGE + ".proxy")
receipts = importlib.import_module(_PACKAGE + ".receipts")


_ENERGY = {
    "state": "UNAVAILABLE",
    "measured_joules": None,
    "estimated_joules": None,
    "measurement_mode": None,
    "detail": "offline privacy regression; no hardware measurement",
}
_CARBON = {"label": "UNAVAILABLE", "carbon_intensity_gco2_per_kwh": None}
_PAYLOAD = {"model": "offline-test-model", "messages": []}
_UPSTREAM = {"model": "offline-test-model", "choices": [], "usage": {}}
_CASES = (
    (),
    (("Authorization", ""),),
    (("Authorization", "Bearer INERT_SHORT_ALPHA"),),
    (("aUtHoRiZaTiOn", "Bearer INERT_LONG_BRAVO_" + "x" * 100),),
    (("Authorization", "Basic INERT_BASIC_CHARLIE"),),
    (("Authorization", "INERT_CUSTOM_DELTA"),),
    (("Authorization", "Bearer INERT_DUPLICATE_ECHO"),
     ("Authorization", "Bearer INERT_DUPLICATE_FOXTROT")),
    (("Proxy-Authorization", "Bearer INERT_PROXY_GOLF"),
     ("X-API-Key", "INERT_API_HOTEL"),
     ("X-Requester-ID", "INERT_FORGED_INDIA")),
)


@unittest.skipUnless(proxy._HAVE_WEB, "requires the project's [proxy] extra")
class RequesterPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.upstream = Mock()
        self.upstream.post.return_value.json.return_value = _UPSTREAM
        self.stack.enter_context(patch.object(proxy.httpx, "Client", return_value=self.upstream))
        self.stack.enter_context(patch.object(proxy, "EnergyState", return_value=Mock()))
        measurement = SimpleNamespace(wall_seconds=0.0, as_receipt_energy=lambda: dict(_ENERGY))
        self.stack.enter_context(patch.object(
            proxy, "measure_inference_energy", side_effect=lambda state, call: (call(), measurement)
        ))
        self.stack.enter_context(patch.object(proxy, "fetch_carbon_context", return_value=_CARBON))
        self.key_loader = self.stack.enter_context(patch.object(proxy, "_load_signing_key", return_value=None))
        # Every app argument is explicit, and environment access is forbidden.
        self.stack.enter_context(patch.object(proxy, "os", SimpleNamespace(environ={})))

    def app(self):
        return proxy.create_app(upstream_base="https://upstream.invalid", store_dir="/inert-memory-store")

    def assert_no_header_fragments(self, value):
        serialized = json.dumps(value, sort_keys=True)
        self.assertNotIn("INERT_", serialized)
        for headers in _CASES:
            for _, header in headers:
                if header:
                    self.assertNotIn(header, serialized)
                    self.assertNotIn(header[:64], serialized)
                    self.assertNotIn(header.split()[-1], serialized)

    def test_request_headers_never_reach_issuer(self):
        issuer = Mock()
        issuer.issue.return_value = {
            "body": {"receipt_id": "offline-test", "energy": _ENERGY},
            "digest": "offline-digest",
        }
        self.stack.enter_context(patch.object(proxy, "ReceiptIssuer", return_value=issuer))
        app = self.app()
        handler = next(r.endpoint for r in app.routes if r.path == "/v1/chat/completions")

        class RequestWithoutReadableHeaders:
            async def json(self):
                return _PAYLOAD

            @property
            def headers(self):
                raise AssertionError("receipt attribution must not inspect request credentials")

        response = asyncio.run(handler(RequestWithoutReadableHeaders()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body), _UPSTREAM)
        self.assertNotIn("requester", issuer.issue.call_args.kwargs)
        self.assert_no_header_fragments(issuer.issue.call_args.kwargs)
        self.upstream.post.assert_called_once_with(
            "https://upstream.invalid/v1/chat/completions", json=_PAYLOAD
        )

    def test_authorization_is_absent_from_serialized_and_returned_receipts(self):
        # Exercise real ReceiptIssuer construction, body hashing, and JSONL
        # serialization while replacing every disk and signer boundary.
        signing = self.stack.enter_context(patch.object(receipts, "_sign_envelope", return_value=None))
        fake_os = SimpleNamespace(
            makedirs=Mock(), fsync=Mock(),
            path=SimpleNamespace(join=lambda *parts: "/inert-memory-store/receipts.jsonl", exists=Mock(return_value=False)),
        )
        self.stack.enter_context(patch.object(receipts, "os", fake_os))
        storage = mock_open()
        storage.return_value.fileno.return_value = 42
        self.stack.enter_context(patch.object(receipts, "open", storage, create=True))
        self.stack.enter_context(patch.object(receipts.fcntl, "flock"))
        app = self.app()

        async def exercise():
            transport = proxy.httpx.ASGITransport(app=app)
            async with proxy.httpx.AsyncClient(transport=transport, base_url="http://offline.invalid") as client:
                previous_digest = receipts.GENESIS_PREV
                for seq, headers in enumerate(_CASES):
                    with self.subTest(case=seq):
                        response = await client.post("/v1/chat/completions", headers=list(headers), json=_PAYLOAD)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), _UPSTREAM)
                        self.assert_no_header_fragments(dict(response.headers))
                        fetched = await client.get("/receipts/%d" % seq)
                        self.assertEqual(fetched.status_code, 200)
                        record = fetched.json()
                        expected_previous = previous_digest
                        previous_digest = record["digest"]
                        self.assertEqual(record["body"]["requester"], "anonymous")
                        self.assertEqual(record["body"]["prev"], expected_previous)
                        self.assertEqual(receipts.digest_body(record["body"]), record["digest"])
                        self.assertEqual(record["body"]["energy"], _ENERGY)
                        self.assertIsNone(record["signature"])
                        self.assert_no_header_fragments(record)
                        written = storage.return_value.write.call_args.args[0]
                        self.assertTrue(written.endswith("\n"))
                        self.assertEqual(json.loads(written), record)
                        self.assert_no_header_fragments(written)
                listing = await client.get("/receipts")
                self.assertEqual(listing.status_code, 200)
                self.assertEqual(listing.json()["count"], len(_CASES))
                self.assert_no_header_fragments(listing.json())

        asyncio.run(exercise())
        self.assertEqual(storage.return_value.write.call_count, len(_CASES))
        self.assertEqual(fake_os.fsync.call_count, len(_CASES))
        self.assertEqual(self.upstream.post.call_count, len(_CASES))
        self.assertEqual(signing.call_count, len(_CASES) + 1)  # includes constructor probe
        for call in signing.call_args_list:
            self.assertIsNone(call.args[1])
            self.assert_no_header_fragments(call.args[0])
        for call in storage.call_args_list:
            self.assertEqual(call.args, ("/inert-memory-store/receipts.jsonl", "a"))
        for call in self.upstream.post.call_args_list:
            self.assertEqual(call.args, ("https://upstream.invalid/v1/chat/completions",))
            self.assertEqual(call.kwargs, {"json": _PAYLOAD})


if __name__ == "__main__":
    unittest.main()
