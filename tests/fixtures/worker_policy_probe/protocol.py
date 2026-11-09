"""Bounded offline fixture framing, independent of host/runtime imports."""

import json
import os
import select
import time


def read_frame(fd, *, timeout=30, max_bytes=8192):
    """Read one frame under an absolute deadline without buffered read-ahead."""
    deadline = time.monotonic() + timeout
    frame = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError("fixture frame deadline")
        chunk = os.read(fd, 1)
        if not chunk:
            raise EOFError("fixture pipe closed before complete frame")
        frame.extend(chunk)
        if len(frame) > max_bytes:
            raise ValueError("fixture frame exceeds byte limit")
        if chunk == b"\n":
            value = json.loads(frame)
            if type(value) is not dict:
                raise ValueError("fixture frame must be an object")
            return value
