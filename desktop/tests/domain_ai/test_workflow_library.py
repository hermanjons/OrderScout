import pytest
from PyQt6.QtWidgets import QApplication, QDialog

from AI.processors.workflow_store import prepare_workflow_save, save_prepared_workflow
from AI.views.workflow_library import WorkflowLibraryDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _save(root, *, scoped=False):
    definition = {"type": "integer", "description": "Kaç günlük satış?", "minimum": 1, "maximum": 31}
    name = "days"
    if scoped:
        name, definition = "account", {"type": "integer", "description": "Mağaza", "scope": "account_id"}
    spec = {"schema_version": 1, "name": "Satış kontrolü", "instructions": "Kaynakları okuyup eksikleri belirt.",
            "objective_template": "Satışları incele: {{" + name + "}}", "parameter_schema": {
                "type": "object", "properties": {name: definition}, "required": [name], "additionalProperties": False},
            "source_policy": {"description": "Güncel kaynakları oku.", "requires_current_sources": True},
            "effect_policy": {"description": "Gerçek işlemi kullanıcının onayına sun.", "requires_current_approval": True}}
    return save_prepared_workflow(prepare_workflow_save(spec), root=root)


def test_empty_library_does_not_create_store_or_start_work(tmp_path, app):
    dialog = WorkflowLibraryDialog(root=tmp_path)
    assert dialog.run_request is None and dialog.workflow_list.count() == 0
    assert not dialog.run_button.isEnabled()
    assert not dialog.schedule_button.isEnabled() and dialog.requested_mode == "run"
    assert not list(tmp_path.iterdir())
    dialog.deleteLater()


def test_selected_revision_renders_typed_parameters_without_executing_tools(tmp_path, app):
    revision = _save(tmp_path)
    dialog = WorkflowLibraryDialog(root=tmp_path)
    assert "Kaynakları okuyup eksikleri belirt." in dialog.review.toPlainText()
    dialog._fields["days"][1].setText("7")
    dialog._accept_run()
    assert dialog.result() == QDialog.DialogCode.Accepted
    request = dialog.run_request
    assert request.workflow_id == revision.workflow_id and request.revision_id == revision.revision_id
    assert request.spec_hash == revision.spec.content_hash and request.parameters == {"days": 7}
    assert "Satışları incele: 7" in request.objective
    assert "{{" not in request.objective
    assert dialog.requested_mode == "run"
    dialog.deleteLater()


def test_invalid_parameter_does_not_start_a_workflow(tmp_path, app):
    _save(tmp_path)
    dialog = WorkflowLibraryDialog(root=tmp_path)
    dialog._fields["days"][1].setText("1000")
    dialog._accept_run()
    assert dialog.run_request is None and dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error.text()
    dialog.deleteLater()


def test_scoped_parameter_uses_current_typed_bindings(tmp_path, app):
    _save(tmp_path, scoped=True)
    dialog = WorkflowLibraryDialog(root=tmp_path, allowed_scope_bindings={"account_id": [101]})
    field = dialog._fields["account"][1]
    assert field.count() == 1 and field.currentData() == 101
    dialog._accept_run()
    assert dialog.run_request.parameters == {"account": 101}
    dialog.deleteLater()


def test_missing_current_scope_cannot_use_saved_account_authority(tmp_path, app):
    _save(tmp_path, scoped=True)
    dialog = WorkflowLibraryDialog(root=tmp_path)
    dialog._accept_run()
    assert dialog.run_request is None and dialog.error.text()
    dialog.deleteLater()


def test_schedule_request_uses_same_typed_revision_and_parameters_without_writing_a_schedule(tmp_path, app):
    revision = _save(tmp_path)
    dialog = WorkflowLibraryDialog(root=tmp_path)
    dialog._fields["days"][1].setText("7")
    dialog.schedule_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.requested_mode == "schedule"
    request = dialog.run_request
    assert request.workflow_id == revision.workflow_id and request.revision_id == revision.revision_id
    assert request.spec_hash == revision.spec.content_hash and request.parameters == {"days": 7}
    assert "Satışları incele: 7" in request.objective
    assert [path.name for path in tmp_path.iterdir()] == ["workflow_store.sqlite3"]
    dialog.deleteLater()


def test_schedule_request_rejects_invalid_parameters_and_missing_current_scope(tmp_path, app):
    _save(tmp_path)
    dialog = WorkflowLibraryDialog(root=tmp_path)
    dialog._fields["days"][1].setText("1000")
    dialog.schedule_button.click()
    assert dialog.run_request is None and dialog.requested_mode == "run"
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()
    dialog.deleteLater()
    scoped_root = tmp_path / "scoped"
    _save(scoped_root, scoped=True)
    scoped = WorkflowLibraryDialog(root=scoped_root)
    scoped.schedule_button.click()
    assert scoped.run_request is None and scoped.error.text()
    assert scoped.result() != QDialog.DialogCode.Accepted
    scoped.deleteLater()
