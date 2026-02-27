"""Bridge layer between Corvusforge and SAOE-MVP (saoe-core / saoe-openclaw).

This package provides graceful integration points that allow Corvusforge to
operate both standalone (without saoe-core installed) and as a full SAOE
participant (when saoe-core and saoe-openclaw are available on the Python path).

Modules
-------
crypto_bridge
    Wraps ``saoe_core.crypto.keyring`` for envelope signing and PIN hashing.
    Falls back to local ``hashlib``-based stubs when saoe-core is absent.
audit_bridge
    Dual-writes state transitions to the Corvusforge RunLedger **and** the
    saoe-core ``AuditLog`` (when available).
saoe_adapter
    Converts Corvusforge ``EnvelopeBase`` models to/from ``SATLEnvelope``
    for cross-boundary transport.
transport
    Wraps ``saoe_openclaw.shim.AgentShim`` behind a simplified
    ``Transport.send()`` / ``Transport.receive()`` interface.

All saoe-core / saoe-openclaw imports are optional.  When the dependency is
missing every bridge function degrades cleanly — logging a warning the first
time and returning neutral values thereafter.
"""
