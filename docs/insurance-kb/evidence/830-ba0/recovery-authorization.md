# BA0 · 2026-09-05 recovery authorization

User authorization: “继续授权，执行”, accepting the proposed wheel filename fix,
new frozen source identity, and one additional real app image build.

Cumulative build allowance: 2. Previous builds used: 1. Recovery allowance: 1.
The closeout v1 `build_budget` describes the new identity's recovery execution;
it must be read together with this cumulative history, not as the lifetime total.

The previous build exited 1 at runtime step 9/22 after all four Python wheel
SHA256 checks passed. pip rejected `pip-26.2.1.whl` as an invalid wheel filename.
The failure receipt is preserved byte-for-byte at
`d2/failed-initialization-build.json`, SHA256
`3ce8ed6c24c7e50bd7754f940eeaa9c85906d767c1cdd16d5c6e892f8b1307fb`.
It records build_invocations=1 and remains INCOMPLETE because no image was delivered.

Regression RED: packaging.utils.parse_wheel_filename rejected pip-26.2.1
(wrong number of parts) on the original Dockerfile. The fix restores
py3-none-any in download, checksum and install paths for all four locked wheels.
The regression checks valid wheel syntax, distribution, version, tags and exact
agreement with the locked origin filename.

No further real build is authorized if the recovery build fails. G2 remains locked.
