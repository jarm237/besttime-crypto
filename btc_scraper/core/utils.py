import os
import json
import tempfile
from typing import Any


def write_atomic(path: str, data: Any) -> None:
    """Write `data` to `path` atomically.

    - If `data` is dict or list, it will be JSON-dumped with indent=2 and UTF-8.
    - If `data` is bytes/bytearray, it will be written as binary.
    - Otherwise, str(data) will be written.

    The write builds a temporary file in the destination directory and then
    uses ``os.replace`` to atomically move it into place.
    """
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)

    binary = isinstance(data, (bytes, bytearray))

    mode = "wb" if binary else "w"
    encoding = None if binary else "utf-8"

    if not binary:
        if isinstance(data, (dict, list)):
            payload = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            payload = str(data)

    tmp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode=mode, delete=False, dir=dirpath, encoding=encoding) as tf:
            tmp_file = tf.name
            if binary:
                tf.write(data)
            else:
                tf.write(payload)

        os.replace(tmp_file, path)
    finally:
        try:
            if tmp_file and os.path.exists(tmp_file):
                os.remove(tmp_file)
        except Exception:
            pass
