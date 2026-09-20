from __future__ import annotations

from enum import Enum


class ProbeMode(str, Enum):
    AUTO = "auto"
    OFF = "off"
    DEEP = "deep"
