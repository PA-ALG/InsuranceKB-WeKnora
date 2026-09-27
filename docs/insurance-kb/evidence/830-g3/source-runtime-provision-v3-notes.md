# G3 source runtime provisioner — concentrated review round 2

Status: **PRIVATE DRAFT / NOT EXECUTED**. This note describes only the delta
from the root-persisted v2 script. Root remains the sole future executor. The
repository copy of v2 was not changed.

The four independently reproduced review findings are closed in the private
draft:

1. A successful KB or model PUT is followed immediately by a durable
   `*-api-put-succeeded` checkpoint containing only the response SHA-256. The
   subsequent GET remains a separate operation. Fake tests force that GET to
   fail and confirm the success checkpoint already exists.
2. The full expected KB readback recomputes `capabilities` using the existing
   Go `KnowledgeBase.Capabilities()` projection. With Wiki disabled, the
   expected `capabilities.wiki` is false; vector, keyword, graph, and FAQ are
   derived from the updated indexing strategy and unchanged KB type. All other
   nondynamic fields remain under the existing full equality check.
3. Preflight now includes `database` and `user` in `postgres_binding`. Apply
   checks live `DB_NAME`/`DB_USER`, the preflight source identity, and the
   expanded binding before the first mutation, then performs the existing
   exact container/image/network binding comparison.
4. Preflight and apply share one DocReader environment builder. Apply requires
   a dictionary whose keys are confined to the reviewed allowlist plus the
   forced-empty set, rejects CR/LF/NUL, reconstructs the current source view,
   and compares it exactly with the receipt before the first mutation.
   `DOCREADER_ODL_HYBRID_URL`, both external proxy keys, hybrid mode, and gRPC
   port are explicitly forced to `""`, `""`, `"off"`, and `"50051"`.

The first RED log records the original four failures. A second narrow RED log
proves the model PUT checkpoint independently. The final fake suite covers the
new behaviors and the retained inspect, archive, cleanup, STOP, proxy, and
identity boundaries. No real preflight, apply, HTTP request, container change,
database write, provider call, upload, build, pull, or dependency installation
was performed.

Any future preflight must use the final private script bytes and produce a new
receipt containing that script SHA. Receipts produced for v2 cannot authorize
this draft.
