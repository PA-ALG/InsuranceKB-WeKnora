# Task3bb repair scan: software PASS, deployment pending

Root-owned bounded G3-AUTO-3/4 change. Repair now selects scoped identity/timestamp rows after excluding explicit/finalization terminals and blocked/dead-letter root jobs. Failed children and absent roots remain eligible. Public list/get, explicit recovery, outbox and progression unchanged; no migration or model calls.

RED task3bb-red.log:1FAIL4.70s due full snapshot hydration. GREEN task3bb-green.log:32PASS35.66s runtime/store; existing two SQLite FK sort warnings retained. New mixed-history test includes original evidence, SQL capture excludes field/artifact/material tables during five keyset reads, and verifies history unchanged. Ruffformat/check PASS. Independent plan review c2de24bb70782967a2943723c7acf2d60447d1dcfad1cf34c90de79d4a7e9c80; frozen sixfilemanifestbdc42d9bb6bc7064d9efb6f5ce99159ad35d9bd2a7973bcef97497924b159c40; independent code reviewc92587e322898650fb10170d08a5897a492734513e92df199c26ac5daf8a9574,0BLOCKER. Tests validate selection, not PG performance or 46-second preview cause.

Deployment plan: same existing Harness API/worker image replacement, retain exact old env/image for rollback; only after readonly terminal preflight. APP/UI/models/DB/migrations unchanged. Build/smoke/live initially NOT RUN; real CPU/read latency and fresh-product acceptance pending. G3 NOT COMPLETE.
