"""Corvusforge Dashboard -- Full Multi-Agent UI (Streamlit).

Invariant 14: Full Multi-Agent UI provides real-time visibility into
pipeline execution, fleet status, plugin management, and marketplace.

Build Monitor 2.0 as a Streamlit projection -- still never computes truth,
only displays what's in the ledger + fleet memory + plugin registry.
"""

from corvusforge.dashboard.app import create_dashboard

__all__ = ["create_dashboard"]
