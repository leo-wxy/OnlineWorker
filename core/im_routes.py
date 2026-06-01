from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core.storage import AppStorage


IM_ROUTES_DB_NAME = "im_routes.sqlite3"


@dataclass(frozen=True)
class ImRoute:
    im_provider: str
    im_account_id: str
    im_space_id: str
    im_entry_id: str
    im_entry_kind: str
    route_scope: str
    agent_provider: str | None
    workspace_id: str | None
    workspace_path: str | None
    session_id: str | None
    display_name: str | None
    status: str
    source: str
    created_at: int
    updated_at: int
    last_seen_at: int


def default_im_route_db_path() -> Path:
    from config import default_data_dir, get_data_dir

    data_dir = Path(get_data_dir() or default_data_dir())
    return data_dir / IM_ROUTES_DB_NAME


class ImRouteStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else default_im_route_db_path()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS im_routes (
                  im_provider TEXT NOT NULL,
                  im_account_id TEXT NOT NULL DEFAULT 'default',
                  im_space_id TEXT NOT NULL,
                  im_entry_id TEXT NOT NULL,
                  im_entry_kind TEXT NOT NULL DEFAULT 'unknown',

                  route_scope TEXT NOT NULL,
                  agent_provider TEXT,
                  workspace_id TEXT,
                  workspace_path TEXT,
                  session_id TEXT,

                  display_name TEXT,

                  status TEXT NOT NULL DEFAULT 'active',
                  source TEXT NOT NULL DEFAULT 'observed',

                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  last_seen_at INTEGER NOT NULL,

                  PRIMARY KEY (
                    im_provider,
                    im_account_id,
                    im_space_id,
                    im_entry_id
                  ),

                  CHECK (route_scope IN ('agent', 'workspace', 'session', 'unknown')),
                  CHECK (status IN ('active', 'closed', 'deleted', 'unknown')),
                  CHECK (
                    route_scope = 'unknown'
                    OR (
                      route_scope = 'agent'
                      AND agent_provider IS NOT NULL
                      AND workspace_id IS NULL
                      AND session_id IS NULL
                    )
                    OR (
                      route_scope = 'workspace'
                      AND agent_provider IS NOT NULL
                      AND workspace_id IS NOT NULL
                      AND session_id IS NULL
                    )
                    OR (
                      route_scope = 'session'
                      AND agent_provider IS NOT NULL
                      AND workspace_id IS NOT NULL
                      AND session_id IS NOT NULL
                    )
                  )
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_im_routes_entry
                ON im_routes(im_provider, im_account_id, im_space_id, im_entry_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_im_routes_scope
                ON im_routes(agent_provider, workspace_id, session_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_im_routes_seen
                ON im_routes(last_seen_at)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_im_agent_route
                ON im_routes(im_provider, im_account_id, im_space_id, agent_provider)
                WHERE route_scope = 'agent' AND status = 'active'
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_im_workspace_route
                ON im_routes(im_provider, im_account_id, im_space_id, agent_provider, workspace_id)
                WHERE route_scope = 'workspace' AND status = 'active'
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_im_session_route
                ON im_routes(im_provider, im_account_id, im_space_id, agent_provider, workspace_id, session_id)
                WHERE route_scope = 'session' AND status = 'active'
                """
            )

    def migrate_telegram_json_topics(
        self,
        storage: AppStorage,
        chat_id: int | str,
        *,
        account_id: str = "default",
    ) -> None:
        self.initialize()
        space_id = str(chat_id)
        now = _now()
        with self._connect() as conn:
            for tool_name, topic_id in sorted(storage.global_topic_ids.items()):
                if topic_id is None:
                    continue
                self._upsert_route_conn(
                    conn,
                    im_provider="telegram",
                    im_account_id=account_id,
                    im_space_id=space_id,
                    im_entry_id=str(topic_id),
                    im_entry_kind="topic",
                    route_scope="agent",
                    agent_provider=str(tool_name),
                    workspace_id=None,
                    workspace_path=None,
                    session_id=None,
                    display_name=str(tool_name),
                    status="active",
                    source="migrated",
                    now=now,
                )

            for workspace_id, ws in sorted(storage.workspaces.items()):
                tool_name = str(getattr(ws, "tool", "") or _infer_tool_from_workspace_id(workspace_id))
                if ws.topic_id is not None:
                    self._upsert_route_conn(
                        conn,
                        im_provider="telegram",
                        im_account_id=account_id,
                        im_space_id=space_id,
                        im_entry_id=str(ws.topic_id),
                        im_entry_kind="topic",
                        route_scope="workspace",
                        agent_provider=tool_name,
                        workspace_id=str(workspace_id),
                        workspace_path=getattr(ws, "path", None),
                        session_id=None,
                        display_name=getattr(ws, "name", None),
                        status="active",
                        source="migrated",
                        now=now,
                    )
                for session_id, thread in sorted(ws.threads.items()):
                    if thread.topic_id is None:
                        continue
                    self._upsert_route_conn(
                        conn,
                        im_provider="telegram",
                        im_account_id=account_id,
                        im_space_id=space_id,
                        im_entry_id=str(thread.topic_id),
                        im_entry_kind="topic",
                        route_scope="session",
                        agent_provider=tool_name,
                        workspace_id=str(workspace_id),
                        workspace_path=getattr(ws, "path", None),
                        session_id=str(session_id),
                        display_name=getattr(thread, "preview", None),
                        status="active",
                        source="migrated",
                        now=now,
                    )

    def restore_telegram_topic_mirrors(
        self,
        storage: AppStorage,
        chat_id: int | str,
        *,
        account_id: str = "default",
    ) -> None:
        self.initialize()
        for route in self.list_routes(
            im_provider="telegram",
            im_account_id=account_id,
            im_space_id=str(chat_id),
            active_only=True,
        ):
            topic_id = _parse_topic_id(route.im_entry_id)
            if topic_id is None:
                continue
            if route.route_scope == "agent" and route.agent_provider:
                storage.global_topic_ids[route.agent_provider] = topic_id
            elif route.route_scope == "workspace" and route.workspace_id:
                ws = storage.workspaces.get(route.workspace_id)
                if ws is not None:
                    ws.topic_id = topic_id
            elif route.route_scope == "session" and route.workspace_id and route.session_id:
                ws = storage.workspaces.get(route.workspace_id)
                if ws is not None and route.session_id in ws.threads:
                    ws.threads[route.session_id].topic_id = topic_id

    def upsert_telegram_agent_route(
        self,
        chat_id: int | str,
        topic_id: int,
        agent_provider: str,
        *,
        account_id: str = "default",
        display_name: str | None = None,
        source: str = "created_by_bot",
    ) -> None:
        self.upsert_route(
            im_provider="telegram",
            im_account_id=account_id,
            im_space_id=str(chat_id),
            im_entry_id=str(topic_id),
            im_entry_kind="topic",
            route_scope="agent",
            agent_provider=agent_provider,
            display_name=display_name or agent_provider,
            source=source,
        )

    def upsert_telegram_workspace_route(
        self,
        chat_id: int | str,
        topic_id: int,
        *,
        agent_provider: str,
        workspace_id: str,
        workspace_path: str | None = None,
        display_name: str | None = None,
        account_id: str = "default",
        source: str = "created_by_bot",
    ) -> None:
        self.upsert_route(
            im_provider="telegram",
            im_account_id=account_id,
            im_space_id=str(chat_id),
            im_entry_id=str(topic_id),
            im_entry_kind="topic",
            route_scope="workspace",
            agent_provider=agent_provider,
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            display_name=display_name,
            source=source,
        )

    def upsert_telegram_session_route(
        self,
        chat_id: int | str,
        topic_id: int,
        *,
        agent_provider: str,
        workspace_id: str,
        session_id: str,
        workspace_path: str | None = None,
        display_name: str | None = None,
        account_id: str = "default",
        source: str = "created_by_bot",
    ) -> None:
        self.upsert_route(
            im_provider="telegram",
            im_account_id=account_id,
            im_space_id=str(chat_id),
            im_entry_id=str(topic_id),
            im_entry_kind="topic",
            route_scope="session",
            agent_provider=agent_provider,
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            session_id=session_id,
            display_name=display_name,
            source=source,
        )

    def observe_unknown_telegram_entry(
        self,
        chat_id: int | str,
        topic_id: int,
        *,
        account_id: str = "default",
        display_name: str | None = None,
    ) -> None:
        self.upsert_route(
            im_provider="telegram",
            im_account_id=account_id,
            im_space_id=str(chat_id),
            im_entry_id=str(topic_id),
            im_entry_kind="topic",
            route_scope="unknown",
            display_name=display_name,
            status="unknown",
            source="observed",
        )

    def upsert_route(
        self,
        *,
        im_provider: str,
        im_account_id: str = "default",
        im_space_id: str,
        im_entry_id: str,
        im_entry_kind: str = "unknown",
        route_scope: str,
        agent_provider: str | None = None,
        workspace_id: str | None = None,
        workspace_path: str | None = None,
        session_id: str | None = None,
        display_name: str | None = None,
        status: str = "active",
        source: str = "observed",
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            self._upsert_route_conn(
                conn,
                im_provider=im_provider,
                im_account_id=im_account_id,
                im_space_id=im_space_id,
                im_entry_id=im_entry_id,
                im_entry_kind=im_entry_kind,
                route_scope=route_scope,
                agent_provider=agent_provider,
                workspace_id=workspace_id,
                workspace_path=workspace_path,
                session_id=session_id,
                display_name=display_name,
                status=status,
                source=source,
                now=_now(),
            )

    def get_route(
        self,
        im_provider: str,
        im_account_id: str,
        im_space_id: str,
        im_entry_id: str,
    ) -> ImRoute | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM im_routes
                WHERE im_provider = ?
                  AND im_account_id = ?
                  AND im_space_id = ?
                  AND im_entry_id = ?
                """,
                (im_provider, im_account_id, im_space_id, im_entry_id),
            ).fetchone()
        return _route_from_row(row) if row else None

    def get_telegram_route(
        self,
        chat_id: int | str,
        topic_id: int,
        *,
        account_id: str = "default",
        active_only: bool = True,
    ) -> ImRoute | None:
        route = self.get_route("telegram", account_id, str(chat_id), str(topic_id))
        if route is None:
            return None
        if active_only and route.status != "active":
            return None
        return route

    def get_telegram_agent_topic_id(
        self,
        chat_id: int | str,
        agent_provider: str,
        *,
        account_id: str = "default",
    ) -> int | None:
        route = self._get_target_route(
            "telegram",
            account_id,
            str(chat_id),
            route_scope="agent",
            agent_provider=agent_provider,
            workspace_id=None,
            session_id=None,
        )
        return _parse_topic_id(route.im_entry_id) if route else None

    def get_telegram_workspace_topic_id(
        self,
        chat_id: int | str,
        *,
        agent_provider: str,
        workspace_id: str,
        account_id: str = "default",
    ) -> int | None:
        route = self._get_target_route(
            "telegram",
            account_id,
            str(chat_id),
            route_scope="workspace",
            agent_provider=agent_provider,
            workspace_id=workspace_id,
            session_id=None,
        )
        return _parse_topic_id(route.im_entry_id) if route else None

    def get_telegram_session_topic_id(
        self,
        chat_id: int | str,
        *,
        agent_provider: str,
        workspace_id: str,
        session_id: str,
        account_id: str = "default",
    ) -> int | None:
        route = self._get_target_route(
            "telegram",
            account_id,
            str(chat_id),
            route_scope="session",
            agent_provider=agent_provider,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        return _parse_topic_id(route.im_entry_id) if route else None

    def list_routes(
        self,
        *,
        im_provider: str | None = None,
        im_account_id: str | None = None,
        im_space_id: str | None = None,
        active_only: bool = False,
    ) -> list[ImRoute]:
        self.initialize()
        clauses: list[str] = []
        params: list[str] = []
        if im_provider is not None:
            clauses.append("im_provider = ?")
            params.append(im_provider)
        if im_account_id is not None:
            clauses.append("im_account_id = ?")
            params.append(im_account_id)
        if im_space_id is not None:
            clauses.append("im_space_id = ?")
            params.append(im_space_id)
        if active_only:
            clauses.append("status = 'active'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM im_routes
                {where}
                ORDER BY im_provider, im_space_id, CAST(im_entry_id AS INTEGER), im_entry_id
                """,
                tuple(params),
            ).fetchall()
        return [_route_from_row(row) for row in rows]

    def _get_target_route(
        self,
        im_provider: str,
        im_account_id: str,
        im_space_id: str,
        *,
        route_scope: str,
        agent_provider: str,
        workspace_id: str | None,
        session_id: str | None,
    ) -> ImRoute | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM im_routes
                WHERE im_provider = ?
                  AND im_account_id = ?
                  AND im_space_id = ?
                  AND route_scope = ?
                  AND agent_provider = ?
                  AND (? IS NULL OR workspace_id = ?)
                  AND (? IS NULL OR session_id = ?)
                  AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (
                    im_provider,
                    im_account_id,
                    im_space_id,
                    route_scope,
                    agent_provider,
                    workspace_id,
                    workspace_id,
                    session_id,
                    session_id,
                ),
            ).fetchone()
        return _route_from_row(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _upsert_route_conn(self, conn: sqlite3.Connection, **kwargs) -> None:
        now = int(kwargs.pop("now"))
        values = {
            "im_provider": kwargs["im_provider"],
            "im_account_id": kwargs["im_account_id"],
            "im_space_id": kwargs["im_space_id"],
            "im_entry_id": kwargs["im_entry_id"],
            "im_entry_kind": kwargs["im_entry_kind"],
            "route_scope": kwargs["route_scope"],
            "agent_provider": kwargs.get("agent_provider"),
            "workspace_id": kwargs.get("workspace_id"),
            "workspace_path": kwargs.get("workspace_path"),
            "session_id": kwargs.get("session_id"),
            "display_name": kwargs.get("display_name"),
            "status": kwargs.get("status", "active"),
            "source": kwargs.get("source", "observed"),
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }
        if values["status"] == "active" and values["route_scope"] != "unknown":
            self._close_existing_active_target_routes(conn, values, now)
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        update_columns = [
            "im_entry_kind",
            "route_scope",
            "agent_provider",
            "workspace_id",
            "workspace_path",
            "session_id",
            "display_name",
            "status",
            "source",
            "updated_at",
            "last_seen_at",
        ]
        update_sql = ", ".join(f"{name} = excluded.{name}" for name in update_columns)
        conn.execute(
            f"""
            INSERT INTO im_routes ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(im_provider, im_account_id, im_space_id, im_entry_id)
            DO UPDATE SET {update_sql}
            """,
            tuple(values[column] for column in columns),
        )

    def _close_existing_active_target_routes(
        self,
        conn: sqlite3.Connection,
        values: dict,
        now: int,
    ) -> None:
        params: list[object] = [
            now,
            values["im_provider"],
            values["im_account_id"],
            values["im_space_id"],
            values["im_entry_id"],
            values["route_scope"],
            values["agent_provider"],
        ]
        where = [
            "im_provider = ?",
            "im_account_id = ?",
            "im_space_id = ?",
            "im_entry_id <> ?",
            "route_scope = ?",
            "agent_provider = ?",
            "status = 'active'",
        ]
        if values["workspace_id"] is None:
            where.append("workspace_id IS NULL")
        else:
            where.append("workspace_id = ?")
            params.append(values["workspace_id"])
        if values["session_id"] is None:
            where.append("session_id IS NULL")
        else:
            where.append("session_id = ?")
            params.append(values["session_id"])
        conn.execute(
            f"""
            UPDATE im_routes
            SET status = 'closed',
                updated_at = ?
            WHERE {" AND ".join(where)}
            """,
            tuple(params),
        )


def _route_from_row(row: sqlite3.Row) -> ImRoute:
    return ImRoute(
        im_provider=row["im_provider"],
        im_account_id=row["im_account_id"],
        im_space_id=row["im_space_id"],
        im_entry_id=row["im_entry_id"],
        im_entry_kind=row["im_entry_kind"],
        route_scope=row["route_scope"],
        agent_provider=row["agent_provider"],
        workspace_id=row["workspace_id"],
        workspace_path=row["workspace_path"],
        session_id=row["session_id"],
        display_name=row["display_name"],
        status=row["status"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_seen_at=row["last_seen_at"],
    )


def _now() -> int:
    return int(time.time())


def _parse_topic_id(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _infer_tool_from_workspace_id(workspace_id: str) -> str:
    prefix, sep, _rest = workspace_id.partition(":")
    return prefix if sep and prefix else ""
