"""Tests for PopulateInstructionsObserver."""
from unittest.mock import MagicMock, patch

from agento.modules.agent_view.src.observers import PopulateInstructionsObserver


def _make_event(artifacts_dir="", agent_view_id=None):
    """Create a minimal AgentViewRunStartedEvent-like object."""
    event = MagicMock()
    event.artifacts_dir = artifacts_dir
    event.agent_view_id = agent_view_id
    return event


def _make_agent_view(id=1, workspace_id=10):
    av = MagicMock()
    av.id = id
    av.workspace_id = workspace_id
    return av


class TestObserverSkips:
    def test_skips_when_no_artifacts_dir(self):
        observer = PopulateInstructionsObserver()
        event = _make_event(artifacts_dir="", agent_view_id=1)

        observer.execute(event)  # should not raise

    def test_skips_when_no_agent_view_id(self):
        observer = PopulateInstructionsObserver()
        event = _make_event(artifacts_dir="/tmp/run/1", agent_view_id=None)

        observer.execute(event)  # should not raise


class TestObserverWritesFiles:
    @patch("agento.modules.agent_view.src.observers.write_instruction_files")
    @patch("agento.modules.agent_view.src.observers.build_scoped_overrides")
    @patch("agento.modules.agent_view.src.observers.get_agent_view")
    @patch("agento.modules.agent_view.src.observers.get_connection")
    def test_writes_files_to_artifacts_dir(self, mock_conn, mock_get_av, mock_overrides, mock_write):
        mock_conn.return_value = MagicMock()
        mock_get_av.return_value = _make_agent_view(id=1, workspace_id=10)
        mock_overrides.return_value = {"agent_view/instructions/agents_md": ("custom", False)}

        observer = PopulateInstructionsObserver()
        event = _make_event(artifacts_dir="/tmp/run/42", agent_view_id=1)
        observer.execute(event)

        mock_overrides.assert_called_once_with(
            mock_conn.return_value, agent_view_id=1, workspace_id=10,
        )
        mock_write.assert_called_once_with(
            "/tmp/run/42", {"agent_view/instructions/agents_md": ("custom", False)},
        )

    @patch("agento.modules.agent_view.src.observers.write_instruction_files")
    @patch("agento.modules.agent_view.src.observers.build_scoped_overrides")
    @patch("agento.modules.agent_view.src.observers.get_agent_view", return_value=None)
    @patch("agento.modules.agent_view.src.observers.get_connection")
    def test_skips_when_agent_view_not_found(self, mock_conn, mock_get_av, mock_overrides, mock_write):
        mock_conn.return_value = MagicMock()

        observer = PopulateInstructionsObserver()
        event = _make_event(artifacts_dir="/tmp/run/42", agent_view_id=999)
        observer.execute(event)

        mock_write.assert_not_called()


class TestObserverErrorHandling:
    @patch("agento.modules.agent_view.src.observers.get_connection", side_effect=RuntimeError("DB down"))
    def test_handles_db_error_gracefully(self, mock_conn):
        observer = PopulateInstructionsObserver()
        event = _make_event(artifacts_dir="/tmp/run/42", agent_view_id=1)

        observer.execute(event)  # should not raise

    @patch("agento.modules.agent_view.src.observers.write_instruction_files", side_effect=OSError("disk full"))
    @patch("agento.modules.agent_view.src.observers.build_scoped_overrides", return_value={})
    @patch("agento.modules.agent_view.src.observers.get_agent_view")
    @patch("agento.modules.agent_view.src.observers.get_connection")
    def test_handles_write_error_gracefully(self, mock_conn, mock_get_av, mock_overrides, mock_write):
        mock_conn.return_value = MagicMock()
        mock_get_av.return_value = _make_agent_view()

        observer = PopulateInstructionsObserver()
        event = _make_event(artifacts_dir="/tmp/run/42", agent_view_id=1)

        observer.execute(event)  # should not raise
