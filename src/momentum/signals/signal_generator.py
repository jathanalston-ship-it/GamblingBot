"""Signal generation orchestrator.

Superseded: scans emit entry signals directly (``api/actions.run_scan``) and
the daily paper pipeline journals its own signals — a separate generator
layer was never needed.
"""
