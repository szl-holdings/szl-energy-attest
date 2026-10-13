# Changelog

Released versions are published to PyPI from GitHub Releases tagged `v<version>`
(see `.github/workflows/publish-pypi.yml`). Entries before 0.3.3 were recorded only
in GitHub Release notes.

## 0.3.3 (unreleased)

Security release for the meter proxy (`szl_energy_attest.meter_proxy`). Upgrade if
you run the proxy. No other public API changes.

### Security

- **Request credentials no longer become receipt identity.** In 0.3.2,
  `POST /v1/chat/completions` in `szl_energy_attest/meter_proxy/proxy.py` set each
  receipt's `requester` field to the first 64 characters of the caller's
  `Authorization` header. That text, which is a Bearer or Basic credential for
  typical clients, was:
  - placed in the receipt body, which is hashed and, when a signing key is
    configured, DSSE-signed;
  - appended with `fsync` to the durable store `receipts.jsonl` under
    `SZL_RECEIPT_DIR` (default `./szl-receipts`);
  - returned in full by `GET /receipts/{seq}`, which the proxy serves without
    authentication.

  A `Bearer` token of 57 characters or fewer was stored whole. Longer values were
  stored truncated to 64 characters. The proxy now reads no request header for
  attribution, and every receipt carries the issuer default
  `requester: "anonymous"`. The source fix was merged on 2026-10-08 (#58) with
  eight offline header cases in `tests/test_proxy_requester_privacy.py`. 0.3.3 is
  the first PyPI release that contains it. The 0.3.1 tag source has the same code
  under the top-level `energy_meter_proxy` import name. 0.3.0 does not ship the
  proxy.
- **Grid-provider error text no longer enters receipts.**
  `szl_energy_attest/meter_proxy/grid.py` stored the full text of any carbon-feed
  fetch exception in the carbon block's `reason`. That block is part of every
  receipt, so the text was written to the same store and returned by the same
  route. The text can include network detail. If the configured
  `SZL_GRID_API_KEY` contains a line break, the Python standard library rejects
  the outbound header with an error that repeats the whole header value, key
  included. The reason now records only the exception class, as the parent
  package's `_grid.py` already did. Regression tests:
  `tests/test_meter_proxy_grid_privacy.py`.

**Exposure is UNKNOWN.** The project does not know which installations of 0.3.2
(or 0.3.1) ran the meter proxy, which credentials passed through it, or who read a
receipt store or the `/receipts` routes. No incident has been confirmed. If you
ran the proxy from one of those versions:

- rotate any credential that clients sent through it;
- restrict access to existing `receipts.jsonl` files and treat their `requester`
  values as credential material.

Editing a stored receipt changes its digest and breaks the hash chain, so
re-anchor deliberately.
