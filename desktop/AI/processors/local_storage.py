"""Shared download capacity policy for the model manager and downloader."""
from pathlib import Path
import shutil

DOWNLOAD_RESERVE_BYTES = 2 * 1024**3


def model_download_capacity(directory, size_bytes, *, partial_bytes=0):
    path = Path(directory)
    while not path.exists() and path.parent != path:
        path = path.parent
    free = int(shutil.disk_usage(str(path)).free)
    remaining = max(0, int(size_bytes or 0) - int(partial_bytes or 0))
    required = remaining + DOWNLOAD_RESERVE_BYTES
    return {"free_bytes": free, "remaining_bytes": remaining, "required_bytes": required,
            "reserve_bytes": DOWNLOAD_RESERVE_BYTES, "allowed": free >= required}
