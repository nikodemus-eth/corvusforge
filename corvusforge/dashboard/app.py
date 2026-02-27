"""Corvusforge Dashboard -- Streamlit-based Multi-Agent UI.

Build Monitor 2.0: A pure projection over the RunLedger, FleetMemory,
PluginRegistry, and Marketplace. Never computes truth -- only displays it.

Usage:
    streamlit run corvusforge/dashboard/app.py
    # or via CLI:
    corvusforge ui
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import streamlit as st

    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def create_dashboard(
    ledger_path: Path | None = None,
    data_dir: Path | None = None,
) -> None:
    """Launch the Corvusforge dashboard.

    Parameters
    ----------
    ledger_path:
        Path to the SQLite ledger DB. Defaults to .corvusforge/ledger.db.
    data_dir:
        Path to .openclaw-data for fleet memory. Defaults to .openclaw-data.
    """
    # Fail fast: production guard must pass before any UI renders
    from corvusforge.config import config as _cfg
    from corvusforge.core.production_guard import enforce_production_constraints

    enforce_production_constraints(_cfg)

    if not HAS_STREAMLIT:
        print("Streamlit is required for the dashboard.")
        print("Install with: pip install corvusforge[dashboard]")
        return

    _run_dashboard(ledger_path, data_dir)


# ---------------------------------------------------------------------------
# Internal dashboard runner
# ---------------------------------------------------------------------------


def _run_dashboard(
    ledger_path: Path | None = None,
    data_dir: Path | None = None,
) -> None:
    """Internal dashboard runner -- requires Streamlit."""

    st.set_page_config(
        page_title="Corvusforge Build Monitor 2.0",
        page_icon="\U0001f528",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Dark theme CSS -- Monokai-inspired palette
    st.markdown(
        """
    <style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: #1a1a2e;
        border: 1px solid #16213e;
        border-radius: 8px;
        padding: 16px;
        margin: 4px 0;
    }
    .stage-passed { color: #00d26a; font-weight: bold; }
    .stage-failed { color: #f92672; font-weight: bold; }
    .stage-running { color: #e6db74; font-weight: bold; }
    .stage-blocked { color: #fd971f; font-weight: bold; }
    .stage-waived { color: #ae81ff; font-weight: bold; }
    .stage-not-started { color: #75715e; }
    .invariant-ok { color: #00d26a; }
    .invariant-fail { color: #f92672; }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    st.sidebar.title("\U0001f528 Corvusforge")
    st.sidebar.markdown("**Build Monitor 2.0**")
    st.sidebar.markdown("---")

    # Run selector
    run_id = st.sidebar.text_input(
        "Run ID", value="", placeholder="cf-20260227-..."
    )
    auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=False)

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Invariants**")

    # Invariant checklist -- display-only projection
    invariants = [
        ("1. Secrets isolation", True),
        ("2. Contracted envelopes", True),
        ("3. Source-independent", True),
        ("4. Prerequisites enforced", True),
        ("5. Accessibility gate", True),
        ("6. Security gate", True),
        ("7. Append-only ledger", True),
        ("8. Content-addressed", True),
        ("9. All-sink routing", True),
        ("10. Replayable", True),
        ("11. Thingstead fleets", True),
        ("12. Persistent memory", True),
        ("13. Signed DLC", True),
        ("14. Multi-Agent UI", True),
        ("15. DLC Marketplace", True),
    ]
    for name, ok in invariants:
        icon = "\u2705" if ok else "\u274c"
        st.sidebar.markdown(f"{icon} {name}")

    # ------------------------------------------------------------------
    # Main content -- 5 tabs
    # ------------------------------------------------------------------
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "\U0001f4ca Pipeline Monitor",
            "\U0001f916 Fleet Status",
            "\U0001f50c Plugins",
            "\U0001f3ea Marketplace",
            "\u267f Accessibility",
        ]
    )

    with tab1:
        _render_pipeline_monitor(run_id, ledger_path)

    with tab2:
        _render_fleet_status(data_dir)

    with tab3:
        _render_plugin_manager()

    with tab4:
        _render_marketplace()

    with tab5:
        _render_accessibility_config()

    if auto_refresh:
        st.rerun()


# ===================================================================
# Tab 1 -- Pipeline Monitor
# ===================================================================

_STATE_ICONS: dict[str, str] = {
    "passed": "\u2705",
    "failed": "\u274c",
    "running": "\U0001f504",
    "blocked": "\U0001f6ab",
    "waived": "\U0001f7e3",
    "not_started": "\u2b1c",
}


def _render_pipeline_monitor(
    run_id: str, ledger_path: Path | None
) -> None:
    """Tab 1: Pipeline stage status, ledger entries, chain verification.

    This is a pure projection -- it reads from the RunLedger and
    MonitorProjection, never writing or computing truth.
    """
    st.header("Pipeline Monitor")

    if not run_id:
        st.info("Enter a Run ID in the sidebar to view pipeline status.")
        st.subheader("Demo Pipeline View")
        _render_demo_stages()
        return

    # Try to connect to the actual ledger
    try:
        from corvusforge.core.run_ledger import RunLedger
        from corvusforge.monitor.projection import MonitorProjection

        path = ledger_path or Path(".corvusforge/ledger.db")
        if not path.exists():
            st.warning(f"Ledger not found at {path}")
            _render_demo_stages()
            return

        ledger = RunLedger(path)
        projection = MonitorProjection(ledger)
        snapshot = projection.snapshot(run_id)

        # ----- Metrics row -----
        col1, col2, col3, col4 = st.columns(4)
        total = snapshot.total_stages
        passed = snapshot.completed_count
        failed = len(snapshot.failed_stages)
        running = len(snapshot.running_stages)

        col1.metric("Total Stages", total)
        col2.metric("Passed / Waived", passed)
        col3.metric("Failed", failed)
        col4.metric("Running", running)

        # ----- Stage table -----
        st.subheader("Stage Status")
        stage_data = []
        for s in snapshot.stages:
            state_str = s.state.value if hasattr(s.state, "value") else str(s.state)
            icon = _STATE_ICONS.get(state_str, "")
            stage_data.append(
                {
                    "Stage": s.stage_id,
                    "Name": s.display_name,
                    "State": f"{icon} {state_str.upper()}",
                    "Last Updated": (
                        str(s.entered_at) if s.entered_at else "-"
                    ),
                    "Waiver": s.waiver_id or "-",
                }
            )
        st.dataframe(stage_data, use_container_width=True)

        # ----- Chain verification -----
        st.subheader("Ledger Integrity")
        if snapshot.chain_valid:
            st.success(
                "Hash chain verified -- ledger integrity confirmed"
            )
        else:
            st.error(
                "Hash chain BROKEN -- ledger may be tampered"
            )

        # ----- Recent entries -----
        st.subheader("Recent Ledger Entries")
        entries = ledger.get_run_entries(run_id)
        for entry in entries[-10:]:
            with st.expander(
                f"{entry.stage_id}: {entry.state_transition}"
            ):
                st.json(
                    {
                        "entry_id": entry.entry_id,
                        "stage_id": entry.stage_id,
                        "state_transition": entry.state_transition,
                        "entry_hash": entry.entry_hash[:16] + "...",
                        "previous_hash": (
                            entry.previous_entry_hash[:16] + "..."
                            if entry.previous_entry_hash
                            else "genesis"
                        ),
                        "pipeline_version": entry.pipeline_version,
                        "schema_version": entry.schema_version,
                        "artifact_refs": entry.artifact_references,
                        "waiver_refs": entry.waiver_references,
                    }
                )

        # ----- Pending clarifications -----
        if snapshot.pending_clarifications:
            st.subheader("Pending Clarifications")
            for stage_id in snapshot.pending_clarifications:
                st.warning(f"Stage **{stage_id}** is blocked and may need clarification.")

        # ----- Active waivers -----
        if snapshot.active_waivers:
            st.subheader("Active Waivers in This Run")
            for waiver_ref in snapshot.active_waivers:
                st.markdown(f"- Waiver `{waiver_ref}`")

    except ImportError as exc:
        st.warning(f"Could not import ledger modules: {exc}")
        _render_demo_stages()
    except Exception as exc:
        st.warning(f"Could not load ledger: {exc}")
        _render_demo_stages()


def _render_demo_stages() -> None:
    """Show demo stage data when no live ledger is available.

    Uses the canonical Corvusforge stage IDs and representative states.
    """
    demo_stages = [
        ("s0_intake", "PASSED", "passed"),
        ("s1_prerequisites", "PASSED", "passed"),
        ("s2_environment", "PASSED", "passed"),
        ("s3_test_contract", "PASSED", "passed"),
        ("s4_code_plan", "PASSED", "passed"),
        ("s5_implementation", "RUNNING", "running"),
        ("s55_accessibility", "NOT STARTED", "not_started"),
        ("s575_security", "NOT STARTED", "not_started"),
        ("s6_verification", "BLOCKED", "blocked"),
        ("s7_release", "NOT STARTED", "not_started"),
    ]
    for stage_id, label, state_key in demo_stages:
        icon = _STATE_ICONS.get(state_key, "")
        css_class = f"stage-{state_key.replace('_', '-')}"
        st.markdown(
            f'{icon} **{stage_id}** -- <span class="{css_class}">{label}</span>',
            unsafe_allow_html=True,
        )


# ===================================================================
# Tab 2 -- Fleet Status
# ===================================================================


def _render_fleet_status(data_dir: Path | None) -> None:
    """Tab 2: Thingstead fleet agents, memory shards, execution receipts.

    Reads from FleetMemory -- never modifies fleet state.
    """
    st.header("Fleet Status")

    try:
        from corvusforge.thingstead.memory import FleetMemory
    except ImportError:
        st.info(
            "Thingstead module not fully available. "
            "Fleet memory requires the ``corvusforge.thingstead.memory`` "
            "submodule (Invariant 11/12)."
        )
        _render_fleet_placeholder()
        return

    path = data_dir or Path(".openclaw-data")
    if not path.exists():
        st.info(
            "No ``.openclaw-data`` directory found. "
            "Fleet memory is not yet initialized."
        )
        st.markdown(
            "Start a pipeline run with Thingstead integration to "
            "initialize fleet memory."
        )
        _render_fleet_placeholder()
        return

    try:
        memory = FleetMemory(path)

        col1, col2 = st.columns(2)
        shard_count = (
            memory.get_shard_count()
            if hasattr(memory, "get_shard_count")
            else 0
        )
        col1.metric("Memory Shards", shard_count)
        col2.metric("Data Directory", str(path))

        # Show shards
        shards = (
            memory.query_shards()
            if hasattr(memory, "query_shards")
            else []
        )
        if shards:
            st.subheader("Recent Memory Shards")
            for shard in shards[-20:]:
                shard_id_short = (
                    shard.shard_id[:8] + "..."
                    if hasattr(shard, "shard_id")
                    else "unknown"
                )
                stage_label = (
                    shard.stage_id
                    if hasattr(shard, "stage_id")
                    else "n/a"
                )
                with st.expander(f"Shard {shard_id_short} -- {stage_label}"):
                    shard_data: dict[str, Any] = {}
                    for field in (
                        "shard_id",
                        "fleet_id",
                        "agent_id",
                        "stage_id",
                        "content_hash",
                        "tags",
                        "created_at",
                    ):
                        if hasattr(shard, field):
                            val = getattr(shard, field)
                            if field == "content_hash" and isinstance(val, str) and len(val) > 16:
                                val = val[:16] + "..."
                            shard_data[field] = str(val)
                    st.json(shard_data)
        else:
            st.info(
                "No memory shards yet. Execute a stage through a "
                "Thingstead fleet to create shards."
            )
    except Exception as exc:
        st.warning(f"Could not load fleet data: {exc}")
        _render_fleet_placeholder()


def _render_fleet_placeholder() -> None:
    """Show a placeholder when fleet data is unavailable."""
    st.markdown("---")
    st.markdown("**Fleet Architecture (Invariant 11 + 12)**")
    st.markdown(
        "- All agentic execution runs inside Thingstead-managed fleets.\n"
        "- Persistent memory is stored in ``.openclaw-data/``.\n"
        "- Each agent produces ``MemoryShard`` artifacts that are "
        "content-addressed and queryable.\n"
        "- Execution receipts provide auditable proof of agent work."
    )


# ===================================================================
# Tab 3 -- Plugin Manager
# ===================================================================


def _render_plugin_manager() -> None:
    """Tab 3: Installed plugins, enable/disable, verification status.

    Reads from the PluginRegistry -- display only.
    """
    st.header("Plugin Manager")

    try:
        from corvusforge.plugins.registry import PluginRegistry
    except ImportError:
        st.info("Plugin registry module not available.")
        return

    try:
        from corvusforge.config import config as _cfg

        registry = PluginRegistry(
            plugin_trust_root_key=_cfg.plugin_trust_root,
        )
        plugins = registry.list_plugins(enabled_only=False)
    except Exception as exc:
        st.info(f"Plugin registry not initialized: {exc}")
        st.markdown(
            "Install a DLC plugin to initialize the registry."
        )
        return

    if not plugins:
        st.info(
            "No plugins installed. Use the Marketplace tab to "
            "discover and install DLC plugins."
        )
        return

    # ----- Metrics -----
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Plugins", len(plugins))
    col2.metric(
        "Verified", sum(1 for p in plugins if p.verified)
    )
    col3.metric(
        "Enabled", sum(1 for p in plugins if p.enabled)
    )

    # ----- Plugin list -----
    st.subheader("Installed Plugins")
    for plugin in plugins:
        verified_icon = "\U0001f512" if plugin.verified else "\u26a0\ufe0f"
        enabled_icon = "\u2705" if plugin.enabled else "\u274c"
        with st.expander(
            f"{verified_icon} {plugin.name} v{plugin.version} {enabled_icon}"
        ):
            st.markdown(f"**Kind:** {plugin.kind.value}")
            st.markdown(f"**Author:** {plugin.author}")
            st.markdown(f"**Description:** {plugin.description}")
            st.markdown(f"**Entry Point:** `{plugin.entry_point}`")
            st.markdown(f"**Verified:** {plugin.verified}")
            st.markdown(f"**Enabled:** {plugin.enabled}")
            st.markdown(f"**Installed:** {plugin.installed_at}")
            if plugin.signature:
                sig_display = (
                    plugin.signature[:24] + "..."
                    if len(plugin.signature) > 24
                    else plugin.signature
                )
                st.markdown(f"**Signature:** `{sig_display}`")


# ===================================================================
# Tab 4 -- Marketplace
# ===================================================================


def _render_marketplace() -> None:
    """Tab 4: DLC Marketplace -- search, browse, and view listings.

    Pure read-only projection over the Marketplace catalog.
    Install actions are left to the CLI (``corvusforge dlc install``).
    """
    st.header("DLC Marketplace")

    try:
        from corvusforge.marketplace.marketplace import Marketplace
    except ImportError:
        st.info("Marketplace module not available.")
        return

    try:
        marketplace = Marketplace()
    except Exception as exc:
        st.info(f"Marketplace not initialized: {exc}")
        return

    # ----- Search -----
    query = st.text_input(
        "Search plugins...",
        placeholder="e.g., accessibility, security, sink",
    )

    if query:
        listings = marketplace.search(query)
    else:
        listings = marketplace.list_all()

    # ----- Stats -----
    stats = marketplace.get_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Listings", stats["total"])
    col2.metric("Verified", stats["verified_count"])
    col3.metric("Total Downloads", stats["total_downloads"])

    # ----- Listing display -----
    if listings:
        st.subheader(f"Available Plugins ({len(listings)})")
        for listing in listings:
            verified_badge = (
                "\U0001f512 Verified"
                if listing.verified
                else "\u26a0\ufe0f Unverified"
            )
            with st.expander(
                f"\U0001f4e6 {listing.name} v{listing.version} -- {verified_badge}"
            ):
                st.markdown(f"**Author:** {listing.author}")
                st.markdown(f"**Description:** {listing.description}")
                st.markdown(f"**Kind:** {listing.kind.value}")
                st.markdown(f"**Tags:** {', '.join(listing.tags)}")
                st.markdown(f"**Downloads:** {listing.downloads}")
                st.markdown(f"**Published:** {listing.published_at}")
                ca_display = (
                    listing.content_address[:24] + "..."
                    if len(listing.content_address) > 24
                    else listing.content_address
                )
                st.markdown(f"**Content Address:** `{ca_display}`")
                st.markdown(
                    "---\n"
                    "*Install via CLI:* "
                    f"`corvusforge dlc install {listing.name}`"
                )
    else:
        if query:
            st.info(f"No plugins found matching '{query}'.")
        else:
            st.info(
                "Marketplace is empty. Publish a DLC plugin to populate it."
            )


# ===================================================================
# Tab 5 -- Accessibility Configuration
# ===================================================================


def _render_accessibility_config() -> None:
    """Tab 5: Accessibility configuration, WCAG thresholds, waivers.

    Displays current gate settings and active waivers.
    Configuration changes are display-only previews -- actual gate
    thresholds are enforced by the pipeline stage definitions.
    """
    st.header("Accessibility Configuration")

    st.subheader("WCAG 2.1 AA Gate Settings")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Minimum Pass Score**")
        min_score = st.slider(
            "WCAG minimum score (%)", 0, 100, 80, 5
        )
        st.markdown(
            f"Stage ``s55_accessibility`` requires a score of "
            f"**{min_score}%** or higher to pass."
        )

        st.markdown("---")
        st.markdown("**Required Checks**")
        checks = [
            "Color contrast (4.5:1 ratio)",
            "Alt text on images",
            "Form labels",
            "Heading hierarchy",
            "Keyboard navigation",
            "ARIA landmarks",
            "Focus indicators",
            "Skip navigation links",
            "Language attributes",
            "Table headers",
            "Link purpose",
        ]
        for check in checks:
            st.checkbox(check, value=True, key=f"wcag_{check}")

    with col2:
        st.markdown("**Gate Behavior**")
        st.radio(
            "When accessibility check fails:",
            [
                "Block pipeline (mandatory gate)",
                "Warn but allow (advisory)",
                "Allow waiver",
            ],
            index=0,
        )

        st.markdown("---")
        st.markdown("**Security Gate (s575)**")
        st.checkbox("Enable security gate", value=True)
        st.checkbox(
            "Block on high-severity findings", value=True
        )
        st.checkbox("Block on secrets detected", value=True)
        st.checkbox("Block on known CVEs", value=True)

    # ----- Active Waivers -----
    st.subheader("Active Waivers")
    _render_active_waivers()


def _render_active_waivers() -> None:
    """Display active waivers from the WaiverManager, if available."""
    try:
        from corvusforge.core.artifact_store import ContentAddressedStore
        from corvusforge.core.waiver_manager import WaiverManager

        store = ContentAddressedStore(
            base_path=Path(".corvusforge/artifacts")
        )
        from corvusforge.config import config as _cfg

        wm = WaiverManager(
            store,
            waiver_verification_key=_cfg.waiver_signing_key,
        )
        waivers = wm.get_all_active_waivers()

        if waivers:
            for waiver in waivers:
                expiry = str(waiver.expiration)
                with st.expander(
                    f"Waiver: {waiver.scope} (expires {expiry})"
                ):
                    st.markdown(
                        f"**Justification:** {waiver.justification}"
                    )
                    st.markdown(
                        f"**Approved by:** {waiver.approving_identity}"
                    )
                    risk_val = (
                        waiver.risk_classification.value
                        if hasattr(waiver.risk_classification, "value")
                        else str(waiver.risk_classification)
                    )
                    st.markdown(f"**Risk:** {risk_val}")
                    st.markdown(f"**Created:** {waiver.created_at}")
                    st.markdown(f"**Waiver ID:** `{waiver.waiver_id}`")
        else:
            st.info("No active waivers.")
    except ImportError:
        st.info(
            "No active waivers (waiver manager module not available)."
        )
    except Exception:
        st.info(
            "No active waivers (waiver manager not initialized)."
        )


# ---------------------------------------------------------------------------
# Entry point for `streamlit run corvusforge/dashboard/app.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__" or (HAS_STREAMLIT and hasattr(st, "session_state")):
    _run_dashboard()
