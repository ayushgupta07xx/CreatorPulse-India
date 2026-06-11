"""PostHog instrumentation for the CreatorPulse Streamlit app.

Server-side capture via posthog-python 7.x. Every helper no-ops cleanly when no
POSTHOG_API_KEY is set, so the app behaves identically offline and on a fresh
deploy before secrets land. Torch-free — safe to import from any page.
"""

from __future__ import annotations

import hashlib
import os
import uuid

import streamlit as st

_DEFAULT_HOST = "https://us.i.posthog.com"
_FLAG = "match_rerank_v2"


def _read_secret(name: str) -> str | None:
    """st.secrets first (Streamlit Cloud), then process env (.env locally)."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001
        pass
    return os.getenv(name)


@st.cache_resource(show_spinner=False)
def _client():
    """Configure and return the posthog module once per server, or None."""
    key = _read_secret("POSTHOG_API_KEY")
    if not key:
        return None
    import posthog

    posthog.api_key = key
    posthog.host = _read_secret("POSTHOG_HOST") or _DEFAULT_HOST
    posthog.debug = False
    return posthog


def enabled() -> bool:
    return _client() is not None


def distinct_id() -> str:
    """One stable id per browser session, shared across both persona pages."""
    if "cp_distinct_id" not in st.session_state:
        st.session_state["cp_distinct_id"] = uuid.uuid4().hex
    return st.session_state["cp_distinct_id"]


def capture(event: str, props: dict | None = None) -> None:
    """Fire a PostHog event. Never raises — analytics must not break the app."""
    ph = _client()
    if ph is None:
        return
    try:
        ph.capture(event, distinct_id=distinct_id(), properties=props or {})
    except Exception:  # noqa: BLE001
        pass


def capture_once(seen_key: str, event: str, props: dict | None = None) -> None:
    """Fire `event` only the first time `seen_key` is seen this session.

    Streamlit reruns the whole script on every interaction; this guards events
    that would otherwise re-fire on each rerun (persona entry, profile views).
    """
    seen = st.session_state.setdefault("_ph_seen", set())
    if seen_key in seen:
        return
    seen.add(seen_key)
    capture(event, props)


def match_variant() -> str:
    """Return 'test' (Variant B, full two-stage rerank) or 'control' (Variant A).

    Reads the match_rerank_v2 feature flag when PostHog is live; otherwise falls
    back to a deterministic 50/50 split on the session id so the A/B still
    assigns offline and on a keyless deploy.
    """
    did = distinct_id()
    ph = _client()
    if ph is not None:
        try:
            v = ph.get_feature_flag(_FLAG, did)
            if isinstance(v, bool):
                return "test" if v else "control"
            if isinstance(v, str):
                return "test" if v.lower() in ("test", "variant-b", "b", "true") else "control"
        except Exception:  # noqa: BLE001
            pass
    digest = int(hashlib.sha256(did.encode()).hexdigest(), 16)
    return "test" if digest % 2 == 0 else "control"
