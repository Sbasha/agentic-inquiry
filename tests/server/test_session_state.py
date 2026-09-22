"""Tests for agent_vault.server.session.state - Session state management."""

import pytest

from agent_vault.server.session.state import SessionState


@pytest.fixture
def session():
    return SessionState()


@pytest.fixture
def session_custom():
    config = {"checkpoints": {"interval_turns": 3}}
    return SessionState(config)


class TestSessionState:
    """Test session state tracking."""

    def test_initial_state(self, session):
        state = session.get_state()
        assert state["turn"] == 0
        assert state["recent_queries"] == []
        assert state["file_changes"] == 0

    def test_increment_turn(self, session):
        result = session.increment_turn()
        assert result["turn"] == 1
        assert not result["checkpoint"]

    def test_checkpoint_due(self, session):
        # Default interval is 5
        for _ in range(4):
            session.increment_turn()
        result = session.increment_turn()
        assert result["turn"] == 5
        assert result["checkpoint"]

    def test_custom_checkpoint_interval(self, session_custom):
        for _ in range(2):
            session_custom.increment_turn()
        result = session_custom.increment_turn()
        assert result["turn"] == 3
        assert result["checkpoint"]

    def test_add_query(self, session):
        session.add_query("search for auth")
        state = session.get_state()
        assert any(q["query"] == "search for auth" for q in state["recent_queries"])

    def test_query_limit(self, session):
        for i in range(25):
            session.add_query(f"query {i}")
        # Internal list keeps 20
        assert len(session.recent_queries) <= 20

    def test_record_file_change(self, session):
        session.record_file_change("src/main.py", "write")
        assert len(session.pending_changes) == 1
        assert session.pending_changes[0]["file_path"] == "src/main.py"
        assert session.pending_changes[0]["change_type"] == "write"

    def test_clear_changes(self, session):
        session.record_file_change("src/main.py", "write")
        session.record_file_change("src/app.py", "edit")
        count = session.clear_changes()
        assert count == 2
        assert len(session.pending_changes) == 0

    def test_update_state_turn(self, session):
        result = session.update_state(turn=10)
        assert result["updated"] is True
        assert session.turn_count == 10

    def test_update_state_topic(self, session):
        session.update_state(topic="authentication")
        state = session.get_state()
        assert state["topic"] == "authentication"

    def test_update_state_partial(self, session):
        session.update_state(topic="auth")
        session.update_state(turn=5)
        state = session.get_state()
        assert state["topic"] == "auth"
        assert state["turn"] == 5

    def test_turn_count_property(self, session):
        session.increment_turn()
        session.increment_turn()
        assert session.turn_count == 2

    def test_file_changes_count_in_state(self, session):
        session.record_file_change("a.py", "write")
        session.record_file_change("b.py", "edit")
        state = session.get_state()
        assert state["file_changes"] == 2
