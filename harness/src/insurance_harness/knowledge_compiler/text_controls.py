"""Exact control-character checks; regex scans run outside Python character loops."""

import re

BODY_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
STRUCTURED_CONTROLS = re.compile(r"[\x00-\x1f\x7f]")
