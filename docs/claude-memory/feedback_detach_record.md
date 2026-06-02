---
name: Always update _detach_record when adding PatternRecord fields
description: _detach_record() snapshots ORM fields into SimpleNamespace — new columns must be added there too or they crash at runtime
type: feedback
originSessionId: f501baf1-25a0-4127-bd25-05baff95b8a7
---
When adding new columns to PatternRecord, always also add them to `_detach_record()` in `main.py:57-81`. Use `getattr(record, "field", None)` for safety.

**Why:** Adding `pattern_metadata` to PatternRecord without updating `_detach_record` caused a crash after order placement (orders placed in MT5 but DB write failed), creating 4 orphaned positions.

**How to apply:** Any time a new field is added to PatternRecord or TradeRecord that gets accessed via a detached record, update `_detach_record()` and use `getattr` with a default in consuming code.
