"""Explicit, bounded HTTP transports. TLS verification is never disabled."""

import base64
from datetime import datetime, timezone
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

ENDPOINTS = {"fed": "https://www.federalreserve.gov/feeds/press_all.xml", "nbs": "https://www.stats.gov.cn/sj/zxfb/"}
MAX_BYTES = 5 * 1024 * 1024


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname or new.port not in (None, 443) or new.username or new.password:
            raise ValueError("unexpected_source_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(source, *, transport="python"):
    if source not in ENDPOINTS:
        raise ValueError("unknown_source")
    url = ENDPOINTS[source]
    if transport == "python":
        request = Request(url, headers={"User-Agent": "MarketIntelResearch/0.1 (low-frequency internal metadata reader)"})
        with build_opener(OfficialRedirects()).open(request, timeout=20) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("source_too_large")
            return data, {"url": url, "final_url": response.url, "http_status": response.status,
                          "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "transport": "python-verified-https"}
    if transport != "node":
        raise ValueError("unknown_transport")
    executable = os.environ.get("MARKET_INTEL_NODE")
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
        raise ValueError("set_MARKET_INTEL_NODE_to_verified_modern_node")
    # -I-like isolation: inherited Node flags must not disable certificate checks
    # or preload code into the compatibility worker.
    environment = dict(os.environ)
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_TLS_REJECT_UNAUTHORIZED", None)
    worker = str(files("market_intel.transport").joinpath("fetch.mjs"))
    try:
        result = subprocess.run([executable, worker, source], capture_output=True, timeout=25, env=environment, check=False)
    except subprocess.TimeoutExpired as exc:
        raise OSError("node_transport_timeout") from exc
    if result.returncode:
        raise OSError(f"node_transport_failed_exit_{result.returncode}")
    if len(result.stdout) > MAX_BYTES * 2:
        raise ValueError("source_too_large")
    payload = json.loads(result.stdout)
    data = base64.b64decode(payload["data_base64"], validate=True)
    response = payload["response"]
    if len(data) > MAX_BYTES or response["url"] != url or response["final_url"] != url or response["http_status"] != 200:
        raise ValueError("unexpected_transport_response")
    return data, response
