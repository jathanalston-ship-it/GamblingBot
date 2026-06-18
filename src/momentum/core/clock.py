"""Time abstraction decoupling business logic from wall-clock time.

Defines a Clock protocol with SimulatedClock (backtest) and LiveClock (paper/
live) implementations. This is what lets identical strategy/risk code run in
every mode and is the primary defense against look-ahead bias.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
