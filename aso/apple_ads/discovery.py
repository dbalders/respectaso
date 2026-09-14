"""Bounded read-only discovery through documented Apple Ads v1 suggestions.

Suggestion popularity is kept separate from the weekly popularity dataset:
Apple describes it as relative, and phrase search has no country filter.
"""
from django.utils import timezone
from . import api, storage


def connection_status():
    block = storage.load_apple_settings()["apple_ads"]
    ready = storage.has_credentials() and bool(block.get("ad_account_id")) and storage.apple_source_ready()
    return {"connected": ready, "message": "Apple Ads connected" if ready else
            "Connect and verify Apple Ads in Settings to use official suggestions."}


def _filter(field, value, operator="EQUALS"):
    return {"field": field, "operator": operator, "value": value if isinstance(value, list) else [value]}


def _query(kind, filters, country=None):
    credentials = storage.api_credentials()
    account = storage.load_apple_settings()["apple_ads"]["ad_account_id"]
    if not credentials or not account:
        raise RuntimeError("Apple Ads is not configured.")
    body = {"filters": filters, "pagination": {"offset": 0, "pageSize": 50}}
    path = f"/suggestions/{kind}/query"
    data = api._request("POST", path, credentials, json_body=body, ad_account_id=account)
    rows = data.get("result")
    if not isinstance(rows, list):
        raise RuntimeError("Apple's suggestion response format was not recognized.")
    results = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        term = row.get("text" if kind == "keywords" else "phrase")
        if not isinstance(term, str) or not term.strip() or len(term) > 200:
            continue
        value = row.get("popularity")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = None
        results.append({"keyword": term.strip(), "source": f"apple_{kind}",
                        "apple_relative_popularity": value, "country": country,
                        "retrieved_at": timezone.now().isoformat()})
    pagination = data.get("pagination") or {}
    # Preserve the provider response alongside the exact read-only request.
    return {"endpoint": path, "request": body, "response": data, "candidates": results,
            "truncated": isinstance(pagination.get("totalCount"), int) and pagination['totalCount'] > len(rows)}


def discover(*, seed="", app_id="", country="us"):
    if not connection_status()["connected"]:
        return {"status": "unconfigured", "candidates": [], "snapshots": [],
                "warnings": ["Apple Ads is not connected; no Apple suggestion data was used."]}
    snapshots, candidates, warnings = [], [], []
    requests = []
    if app_id:
        filters = [_filter("promotedObjectId", app_id), _filter("promotedObjectType", "APPSTORE_APP"),
                   _filter("countriesOrRegions", [country.upper()], "IN")]
        if seed:
            filters.append(_filter("terms", [seed], "IN"))
        requests.append(("keywords", filters, country.upper()))
    if seed:
        requests.append(("phrases", [_filter("queryType", "SEARCH"), _filter("phrase", seed, "LIKE")], None))
    elif app_id:
        requests.append(("phrases", [_filter("queryType", "SUGGESTION"), _filter("promotedObjectId", app_id),
                                      _filter("promotedObjectType", "APPSTORE_APP")], None))
    for kind, filters, scope in requests:
        try:
            snapshot = _query(kind, filters, scope)
            snapshots.append(snapshot)
            candidates.extend(snapshot['candidates'])
            if snapshot['truncated']:
                warnings.append(f"Apple {kind} discovery was capped at the first 50 results.")
        except (api.AppleAdsError, RuntimeError):
            warnings.append(f"Apple {kind} query was unavailable. Check connection, app access and endpoint support in Settings.")
    if any(c['country'] is None for c in candidates):
        warnings.append("Apple phrase scores have no documented country scope and are not treated as storefront-specific search volume.")
    return {"status": "available" if snapshots else "unavailable", "candidates": candidates,
            "snapshots": snapshots, "warnings": warnings}
