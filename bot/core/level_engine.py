from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Protocol

MAX_LEVEL = 100


@dataclass
class LevelConfig:
    cooldown_seconds: float = 45.0
    xp_per_message_min: int = 12
    xp_per_message_max: int = 24
    announce_every: int = 5
    max_level: int = MAX_LEVEL


@dataclass
class LevelRecord:
    guild_id: int
    user_id: int
    total_xp: int = 0
    level: int = 0
    last_message_ts: float = 0.0


@dataclass
class LevelUpdate:
    record: LevelRecord
    xp_gained: int = 0
    old_level: int = 0
    new_level: int = 0
    reached_role_levels: List[int] = field(default_factory=list)
    should_announce: bool = False

    @property
    def leveled_up(self) -> bool:
        return self.new_level > self.old_level


class LevelStorageAdapter(Protocol):
    def load(self) -> Dict[str, LevelRecord]:
        ...

    def save(self, records: Dict[str, LevelRecord]) -> None:
        ...


class JsonLevelStorage:
    """JSON persistence with atomic writes and backup-based recovery."""

    def __init__(self, file_path: str):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_path = self.path.with_suffix(f"{self.path.suffix}.bak")

    def load(self) -> Dict[str, LevelRecord]:
        if not self.path.exists():
            return {}

        raw = self._load_json_with_recovery()
        records: Dict[str, LevelRecord] = {}
        for key, payload in raw.items():
            try:
                records[key] = LevelRecord(
                    guild_id=int(payload["guild_id"]),
                    user_id=int(payload["user_id"]),
                    total_xp=int(payload.get("total_xp", 0)),
                    level=int(payload.get("level", 0)),
                    last_message_ts=float(payload.get("last_message_ts", 0.0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
        return records

    def save(self, records: Dict[str, LevelRecord]) -> None:
        payload = {
            key: {
                "guild_id": rec.guild_id,
                "user_id": rec.user_id,
                "total_xp": rec.total_xp,
                "level": rec.level,
                "last_message_ts": rec.last_message_ts,
            }
            for key, rec in records.items()
        }

        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())

        if self.path.exists():
            self.path.replace(self.backup_path)
        tmp_path.replace(self.path)

    def _load_json_with_recovery(self) -> dict:
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            if self.backup_path.exists():
                with self.backup_path.open("r", encoding="utf-8") as fh:
                    recovered = json.load(fh)
                self._restore_primary(recovered)
                return recovered
            return {}

    def _restore_primary(self, payload: dict) -> None:
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.recover")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(self.path)


class SQLiteLevelStorage:
    """SQLite-backed persistence for level records."""

    def __init__(self, file_path: str):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS levels (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total_xp INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 0,
                    last_message_ts REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )

    def load(self) -> Dict[str, LevelRecord]:
        records: Dict[str, LevelRecord] = {}
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT guild_id, user_id, total_xp, level, last_message_ts FROM levels"
            ):
                guild_id, user_id, total_xp, level, last_message_ts = row
                key = make_record_key(guild_id, user_id)
                records[key] = LevelRecord(
                    guild_id=guild_id,
                    user_id=user_id,
                    total_xp=total_xp,
                    level=level,
                    last_message_ts=last_message_ts,
                )
        return records

    def save(self, records: Dict[str, LevelRecord]) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM levels")
            conn.executemany(
                """
                INSERT INTO levels (guild_id, user_id, total_xp, level, last_message_ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (rec.guild_id, rec.user_id, rec.total_xp, rec.level, rec.last_message_ts)
                    for rec in records.values()
                ],
            )
            conn.commit()


def make_record_key(guild_id: int, user_id: int) -> str:
    return f"{guild_id}:{user_id}"


class LevelEngine:
    def __init__(
        self,
        storage: LevelStorageAdapter,
        config: Optional[LevelConfig] = None,
        role_milestones: Optional[Dict[int, int]] = None,
    ):
        self.storage = storage
        self.config = config or LevelConfig()
        self.role_milestones = role_milestones or {25: 0, 50: 0, 75: 0, 100: 0}
        self._lock = threading.RLock()
        self.records = self.storage.load()

    @staticmethod
    def xp_for_next_level(current_level: int) -> int:
        if current_level < 0:
            return 0
        if current_level < 25:
            return 80 + (current_level * 12)
        if current_level < 50:
            ramp = current_level - 25
            return 380 + (ramp * 26)
        if current_level < MAX_LEVEL:
            ramp = current_level - 50
            return 1030 + (ramp * 45) + ((ramp * ramp) // 8)
        return 0

    @classmethod
    def total_xp_for_level(cls, level: int) -> int:
        capped = max(0, min(level, MAX_LEVEL))
        total = 0
        for current in range(capped):
            total += cls.xp_for_next_level(current)
        return total

    @classmethod
    def level_from_xp(cls, total_xp: int) -> int:
        xp_left = max(total_xp, 0)
        level = 0
        while level < MAX_LEVEL:
            required = cls.xp_for_next_level(level)
            if xp_left < required:
                break
            xp_left -= required
            level += 1
        return level

    def _get_or_create(self, guild_id: int, user_id: int) -> LevelRecord:
        key = make_record_key(guild_id, user_id)
        record = self.records.get(key)
        if record is None:
            record = LevelRecord(guild_id=guild_id, user_id=user_id)
            self.records[key] = record
        return record

    def process_message(
        self,
        guild_id: int,
        user_id: int,
        timestamp: Optional[float] = None,
    ) -> LevelUpdate:
        now = timestamp if timestamp is not None else time.time()
        with self._lock:
            rec = self._get_or_create(guild_id, user_id)
            if now - rec.last_message_ts < self.config.cooldown_seconds:
                return LevelUpdate(record=rec, old_level=rec.level, new_level=rec.level)

            old_level = rec.level
            rec.last_message_ts = now
            gained = random.randint(self.config.xp_per_message_min, self.config.xp_per_message_max)
            rec.total_xp += gained
            rec.level = min(self.config.max_level, self.level_from_xp(rec.total_xp))
            reached = [
                lvl
                for lvl in sorted(self.role_milestones.keys())
                if old_level < lvl <= rec.level
            ]
            should_announce = rec.level > old_level and any(
                lvl % self.config.announce_every == 0
                for lvl in range(old_level + 1, rec.level + 1)
            )
            self._persist()
            return LevelUpdate(
                record=rec,
                xp_gained=gained,
                old_level=old_level,
                new_level=rec.level,
                reached_role_levels=reached,
                should_announce=should_announce,
            )

    def get_record(self, guild_id: int, user_id: int) -> LevelRecord:
        with self._lock:
            return self._get_or_create(guild_id, user_id)

    def set_level(self, guild_id: int, user_id: int, level: int) -> LevelRecord:
        with self._lock:
            rec = self._get_or_create(guild_id, user_id)
            rec.level = max(0, min(level, self.config.max_level))
            rec.total_xp = self.total_xp_for_level(rec.level)
            self._persist()
            return rec

    def reset_level(self, guild_id: int, user_id: int) -> LevelRecord:
        with self._lock:
            rec = self._get_or_create(guild_id, user_id)
            rec.level = 0
            rec.total_xp = 0
            rec.last_message_ts = 0.0
            self._persist()
            return rec

    def _persist(self) -> None:
        try:
            self.storage.save(self.records)
        except Exception:
            # Best-effort fallback: drop runtime mutation if save fails.
            self.records = self.storage.load()
            raise
