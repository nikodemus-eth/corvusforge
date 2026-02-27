"""Thingstead fleet integration — agent execution in managed fleets.

Corvusforge v0.2 delegates all agentic execution to Thingstead-managed
fleets, with persistent memory in .openclaw-data and signed DLC support.

Invariant 11: All agentic execution inside Thingstead fleets.
Invariant 12: Persistent memory in .openclaw-data.
"""

from corvusforge.thingstead.fleet import ThingsteadFleet, FleetConfig
from corvusforge.thingstead.memory import FleetMemory, MemoryShard

__all__ = ["ThingsteadFleet", "FleetConfig", "FleetMemory", "MemoryShard"]
