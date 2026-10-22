"""Tables of the retired 007 knowledge chain, kept only because Alembic loads them.

harness/migrations/env.py registers ``tables`` and migration 0005 installs the DDL in
``release_guard_ddl_018``. The chain that used them was removed in S7c; the package
re-exports nothing so these two modules stay the only reachable ones.
"""
