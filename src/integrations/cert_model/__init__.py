"""Certification system-of-record (SQLite first cut).

A temporal participant + certification model: participants hold typed roles over
time, roles require credentials over time, participants hold credentials over time,
and compliance is derived as-of any date. See store.py and
docs/certification-architecture.md.
"""
