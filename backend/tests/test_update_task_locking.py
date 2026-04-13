"""Regression tests for DB-backed update task locking."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.helpers import _get_config_store, _get_scheduler, _get_settings, _get_task_store
from app.api.routes import router
from app.core.config_store import ConfigStore
from app.core.task_store import TaskRecord, TaskStore
from app.config import Settings


class _SchedulerStub:
    def __init__(self, guests):
        self.guests = guests

    def trigger_guest_refresh(self, guest_id: str) -> bool:
        return guest_id in self.guests


def _make_guest_routes_app(tmp_path):
    db_path = str(tmp_path / "test.db")
    config_store = ConfigStore(db_path)
    config_store.save({
        "proxmox_hosts": [{
            "id": "pve1",
            "label": "PVE 1",
            "host": "https://pve1.local:8006",
            "token_id": "root@pam!proxmon",
            "token_secret": "secret",
            "node": "pve1",
            "pct_exec_enabled": True,
        }],
    })
    settings = config_store.merge_into_settings(Settings())
    task_store = TaskStore(db_path)
    guest = SimpleNamespace(
        id="pve1:100",
        name="guest-100",
        host_id="pve1",
        type="lxc",
        status="running",
        os_type="debian",
        has_community_script=True,
    )
    scheduler = _SchedulerStub({guest.id: guest})

    app = FastAPI()
    app.state.config_store = config_store
    app.state.settings = settings
    app.dependency_overrides[_get_scheduler] = lambda: scheduler
    app.dependency_overrides[_get_settings] = lambda: settings
    app.dependency_overrides[_get_config_store] = lambda: config_store
    app.dependency_overrides[_get_task_store] = lambda: task_store
    app.include_router(router)
    return app, task_store, guest.id


class TestUpdateTaskLocking:
    def test_reconcile_stale_running_tasks_marks_all_running_tasks(self, tmp_path) -> None:
        store = TaskStore(str(tmp_path / "test.db"))
        store.create(TaskRecord(
            id="os-1",
            guest_id="pve1:100",
            guest_name="guest-100",
            host_id="pve1",
            action="os_update",
            status="running",
            started_at="2026-01-01T00:00:00Z",
        ))
        store.create(TaskRecord(
            id="app-1",
            guest_id="pve1:101",
            guest_name="guest-101",
            host_id="pve1",
            action="app_update",
            status="running",
            started_at="2026-01-01T00:00:00Z",
        ))
        store.create(TaskRecord(
            id="start-1",
            guest_id="pve1:102",
            guest_name="guest-102",
            host_id="pve1",
            action="start",
            status="running",
            started_at="2026-01-01T00:00:00Z",
        ))

        assert store.reconcile_stale_running_tasks() == 3

        os_task = store.get("os-1")
        app_task = store.get("app-1")
        start_task = store.get("start-1")
        assert os_task is not None and os_task.status == "failed"
        assert app_task is not None and app_task.status == "failed"
        assert start_task is not None and start_task.status == "failed"
        assert os_task.detail == "Interrupted by proxmon restart"
        assert app_task.detail == "Interrupted by proxmon restart"
        assert start_task.detail == "Interrupted by proxmon restart"
        assert os_task.finished_at is not None
        assert app_task.finished_at is not None
        assert start_task.finished_at is not None

    def test_os_update_uses_db_running_task_as_lock(self, tmp_path, monkeypatch) -> None:
        import app.api.routes.guests as guests_routes

        app, task_store, guest_id = _make_guest_routes_app(tmp_path)
        client = TestClient(app)

        def _fake_create_task(coro):
            coro.close()
            return SimpleNamespace()

        monkeypatch.setattr(guests_routes.asyncio, "create_task", _fake_create_task)

        first = client.post(f"/api/guests/{guest_id}/os-update")
        assert first.status_code == 200

        running = task_store.list_running_for_guest(guest_id, "os_update")
        assert len(running) == 1

        second = client.post(f"/api/guests/{guest_id}/os-update")
        assert second.status_code == 409
        assert second.json()["detail"] == "An OS update is already running for this guest"

    def test_os_update_scheduling_failure_marks_task_failed(self, tmp_path, monkeypatch) -> None:
        import app.api.routes.guests as guests_routes

        app, task_store, guest_id = _make_guest_routes_app(tmp_path)
        client = TestClient(app)

        def _boom(coro):
            coro.close()
            raise RuntimeError("scheduler offline")

        monkeypatch.setattr(guests_routes.asyncio, "create_task", _boom)

        resp = client.post(f"/api/guests/{guest_id}/os-update")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to schedule OS update"

        tasks = task_store.list_recent()
        assert len(tasks) == 1
        assert tasks[0].action == "os_update"
        assert tasks[0].status == "failed"
        assert tasks[0].detail == "Failed to schedule OS update: scheduler offline"
        assert tasks[0].finished_at is not None
