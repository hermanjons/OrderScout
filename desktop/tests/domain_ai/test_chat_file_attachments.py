from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

from AI.processors import file_workspace
from AI.processors.session_state import AgentSessionState
from AI.views.chat_tab import AITab


@pytest.fixture
def tab(tmp_path):
    app = QApplication.instance() or QApplication([])
    with patch.object(file_workspace, "ATTACHMENTS_ROOT", tmp_path / "imports"):
        widget = AITab()
        try:
            yield widget
        finally:
            widget.close()
            widget.deleteLater()
            # Retain the application until the widget has been disposed.
            assert app is not None


def test_plus_button_imports_selected_file_into_conversation_capability(tab, tmp_path):
    selected = tmp_path / "sales.json"
    selected.write_text('[{"gross_amount":3000,"currency":"TRY"}]', encoding="utf-8")
    with patch("AI.views.chat_tab.QFileDialog.getOpenFileNames", return_value=([str(selected)], "")), \
         patch.object(tab, "_open_model_hub") as model_hub:
        tab.btn_attach.click()
    model_hub.assert_not_called()
    workspace = tab._conversation_state["active_entities"]["file_workspace"]
    attachment = workspace["attachments"][0]
    assert attachment["name"] == "sales.json"
    assert workspace["session_id"] == attachment["session_id"]
    assert str(selected) not in str(attachment)
    assert "sales.json" in tab.transcript.toPlainText()
    selected.write_text("[]", encoding="utf-8")
    observed = file_workspace.read_attachment(attachment_id=attachment["attachment_id"], session_id=workspace["session_id"])
    assert observed.success
    assert "3000" in str(observed.data)


def test_following_task_session_keeps_original_attachment_owner_and_new_chat_revokes_access(tab, tmp_path):
    selected = tmp_path / "first.txt"
    selected.write_text("first observation", encoding="utf-8")
    tab._import_chat_attachments([str(selected)])
    first_workspace = tab._conversation_state["active_entities"]["file_workspace"]
    owner = first_workspace["session_id"]
    next_task = AgentSessionState.from_dict(tab._conversation_state)
    next_task.session_id = "fresh-execution-task"
    tab._conversation_state = next_task.to_dict()
    second = tmp_path / "second.txt"
    second.write_text("second observation", encoding="utf-8")
    tab._import_chat_attachments([str(second)])
    workspace = tab._conversation_state["active_entities"]["file_workspace"]
    assert workspace["session_id"] == owner
    assert [row["session_id"] for row in workspace["attachments"]] == [owner, owner]
    tab._reset_chat()
    assert "file_workspace" not in tab._conversation_state["active_entities"]
    assert tab.btn_attach.toolTip() == "Bu sohbete dosya ekle"


def test_bad_selection_is_reported_without_authorizing_an_attachment(tab, tmp_path):
    selected = tmp_path / "unsupported.exe"
    selected.write_bytes(b"not an import format")
    tab._import_chat_attachments([str(selected)])
    assert tab._conversation_state["active_entities"]["file_workspace"]["attachments"] == []
    assert "Eklenemeyen dosyalar" in tab.transcript.toPlainText()
    assert selected.read_bytes() == b"not an import format"
