"""Corvusforge event routing — dispatches envelopes to all configured sinks (Invariant 9).

The routing subsystem ensures that every communication event reaches all
configured destinations. Sinks are pluggable targets: local files, the
content-addressed artifact store, Telegram notification payloads, email
notification payloads, or any custom sink implementing the BaseSink protocol.

The SinkDispatcher fans out each envelope to every registered sink.
No event is silently dropped.
"""
