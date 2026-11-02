"""Local POSIX JSONL transactions. All writers must use the stable sidecar lock.

The store directory must be operator-owned. This is not a network-filesystem
or hostile-directory protocol. A failed directory fsync after replace has an
ambiguous commit outcome: reload the store before deciding whether to retry.
"""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import tempfile


@contextmanager
def locked_store(path):
    # Lock an inode that is never replaced, before selecting the chain parent.
    with open(str(path) + ".lock", "a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite JSON value: " + value)


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number: " + value)
    return number


def read_records(path):
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    if raw and not raw.endswith(b"\n"):
        raise ValueError("partial final JSONL line; operator recovery required")
    records = []
    for line in raw.splitlines():
        if not line.strip():
            raise ValueError("blank JSONL record")
        record = json.loads(line, object_pairs_hook=_object, parse_constant=_invalid_constant,
                            parse_float=_finite_float)
        if not isinstance(record, dict):
            raise ValueError("JSONL record must be an object")
        records.append(record)
    return records


def validate_chain(records, *, link, genesis, digest, sequence=False):
    previous = genesis
    days = set()
    for index, record in enumerate(records):
        body = record.get("body")
        if not isinstance(body, dict) or digest(body) != record.get("digest"):
            raise ValueError("stored record digest mismatch")
        if body.get(link) != previous:
            raise ValueError("stored chain link mismatch")
        if sequence and (type(body.get("seq")) is not int or body["seq"] != index):
            raise ValueError("stored sequence mismatch")
        if link == "prev_rollup":
            day = body.get("date")
            if not isinstance(day, str) or day in days:
                raise ValueError("invalid or duplicate stored rollup day")
            days.add(day)
        previous = record["digest"]


def write_records(path, records):
    """Replace a complete snapshot; caller holds locked_store for the transaction."""
    encoded = "".join(json.dumps(r, sort_keys=True, allow_nan=False) + "\n" for r in records)
    parent = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".szl-energy-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
