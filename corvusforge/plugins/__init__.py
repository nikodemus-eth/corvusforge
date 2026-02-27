"""Corvusforge Plugin System — signed DLC plugins with ToolGate enforcement.

Invariant 13: All DLC plugins must be signed and verified through ToolGate + SATL.
Plugins extend pipeline stages, add new sinks, or provide custom validators.
"""

from corvusforge.plugins.registry import PluginRegistry, PluginEntry
from corvusforge.plugins.loader import PluginLoader, DLCPackage

__all__ = ["PluginRegistry", "PluginEntry", "PluginLoader", "DLCPackage"]
