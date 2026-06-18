"""Ingestion orchestrator: fetch -> validate -> adjust -> persist.

Incremental and idempotent (safe to re-run); writes raw + adjusted bars and
records data lineage for auditability.

Architecture scaffold only — interface contract described below; NO implementation yet.
See docs/ARCHITECTURE.md for the full module catalog and diagrams.
"""
