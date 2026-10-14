"""
A paused question resumes as the asker AS THEY ARE NOW (WIRED-2).

The approver's authority covers the write; the answer is the asker's,
read under the asker's current grants. An asker deleted or disabled
while the write waited gets nothing resumed, and nothing is read for
them.
"""

from types import SimpleNamespace

from api.routes import _finish_paused_query
from core.notifications import NotificationStore
from core.paused_queries import PausedQueryStore


class _Directory:
    def __init__(self, active):
        self.active = active

    def user_exists(self, user_id):
        return True

    def is_user_disabled(self, user_id):
        return not self.active

    def get_user_record(self, user_id):
        from core.intermediate_layer.auth import UserRecord
        return UserRecord(user_id, "us-west", "editor")


class _Loop:
    def __init__(self):
        self.resumed_as = None

    def resume(self, previous, user, *args, **kwargs):
        self.resumed_as = user
        raise AssertionError("must not resume for an asker who is gone")


def _app(tmp_path, active):
    loop = _Loop()
    app = SimpleNamespace(state=SimpleNamespace(
        runtime_paths=SimpleNamespace(data_dir=tmp_path),
        user_directory=_Directory(active)))
    app.generation = SimpleNamespace(loop=loop, config=SimpleNamespace(query_deadline_seconds=5))
    PausedQueryStore(tmp_path / "paused_queries.db").save("w1", "alice", "q?", [], 2)
    return app, loop


def test_a_disabled_asker_gets_nothing_resumed(tmp_path):
    app, loop = _app(tmp_path, active=False)
    pending = SimpleNamespace(description="d", action_type_name="A")

    _finish_paused_query(app, app.generation, "w1", pending, {"status": "written", "object_ids": ["x"]})

    assert loop.resumed_as is None
    assert NotificationStore(tmp_path / "notifications.db").for_user("alice") == []


def test_a_question_with_nothing_paused_is_left_alone(tmp_path):
    app, loop = _app(tmp_path, active=True)

    _finish_paused_query(app, app.generation, "not-paused", SimpleNamespace(), {"status": "written"})

    assert loop.resumed_as is None
