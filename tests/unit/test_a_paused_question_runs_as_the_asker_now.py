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
    pending = SimpleNamespace(description="d", action_type_name="A", sub_writes=())

    _finish_paused_query(app, app.generation, "w1", pending, {"status": "written", "object_ids": ["x"]})

    assert loop.resumed_as is None
    assert NotificationStore(tmp_path / "notifications.db").for_user("alice") == []


def test_a_question_with_nothing_paused_is_left_alone(tmp_path):
    app, loop = _app(tmp_path, active=True)

    _finish_paused_query(app, app.generation, "not-paused", SimpleNamespace(), {"status": "written"})

    assert loop.resumed_as is None


def test_a_resumed_answer_says_what_is_inferred(tmp_path):
    """R63 on the resumed path: the answer the asker is notified with
    carries the code-written note when its data holds an inferred value."""
    from core.agent.agentic_loop import AgentLoopResult

    class Answering:
        def resume(self, previous, user, *args, **kwargs):
            return AgentLoopResult(gathered=[{
                "step": "get_field", "object_type": "SupportTicket", "object_id": "t1",
                "field_name": "topic", "result": "billing"}])

    class Model:
        def chat(self, *args, **kwargs):
            return "It is about billing."

    app, _ = _app(tmp_path, active=True)
    app.generation = SimpleNamespace(
        loop=Answering(), synthesis_client=Model(),
        config=SimpleNamespace(query_deadline_seconds=5, schema={"SupportTicket": {"fields": {
            "subject": {"type": "data"},
            "topic": {"type": "data", "enrich": {"from": ["subject"], "instruction": "About?",
                                                 "choices": ["billing", "refund"]}}}}}))
    pending = SimpleNamespace(description="d", action_type_name="A", sub_writes=())

    _finish_paused_query(app, app.generation, "w1", pending, {"status": "written", "object_ids": ["x"]})

    [note] = NotificationStore(tmp_path / "notifications.db").for_user("alice")
    assert note.detail.startswith("It is about billing.")
    assert "SupportTicket.topic was chosen by rules a person approved" in note.detail
