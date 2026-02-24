"""
LocalStorageManager — drop-in replacement for AzureFileStorageManager.
Stores data in local JSON files under .brainstem_data/ instead of Azure.
"""

import os
import json
import logging

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".brainstem_data")


class AzureFileStorageManager:
    """
    Local-first shim that mirrors the AzureFileStorageManager API.
    Imported as `from utils.azure_file_storage import AzureFileStorageManager`
    by remote agents — they get this local version transparently.
    """

    def __init__(self, share_name=None, **kwargs):
        self.current_guid = None
        self._share = share_name or "memory"
        os.makedirs(_DATA_DIR, exist_ok=True)

    # ── Context ───────────────────────────────────────────────────────────

    def set_memory_context(self, user_guid=None):
        """Set the user context for memory operations."""
        self.current_guid = user_guid

    # ── Core I/O ──────────────────────────────────────────────────────────

    def _file_path(self):
        if self.current_guid:
            folder = os.path.join(_DATA_DIR, self.current_guid)
        else:
            folder = os.path.join(_DATA_DIR, "shared")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"{self._share}.json")

    def read_json(self, file_path=None):
        """Read JSON data from local storage."""
        path = file_path or self._file_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def write_json(self, data, file_path=None):
        """Write JSON data to local storage."""
        path = file_path or self._file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return True

    # ── Convenience methods used by some agents ───────────────────────────

    def read_file(self, file_path):
        full = os.path.join(_DATA_DIR, file_path)
        if not os.path.exists(full):
            return None
        with open(full, "r") as f:
            return f.read()

    def write_file(self, file_path, content):
        full = os.path.join(_DATA_DIR, file_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        return True

    def list_files(self, directory=""):
        full = os.path.join(_DATA_DIR, directory)
        if not os.path.exists(full):
            return []
        return os.listdir(full)

    def delete_file(self, file_path):
        full = os.path.join(_DATA_DIR, file_path)
        if os.path.exists(full):
            os.remove(full)
            return True
        return False

    def file_exists(self, file_path):
        return os.path.exists(os.path.join(_DATA_DIR, file_path))
