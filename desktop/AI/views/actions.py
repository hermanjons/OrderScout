from __future__ import annotations

from Feedback.processors.pipeline import Result
from Core.processors.report_artifacts import export_report_snapshot_xlsx

from AI.processors.pipeline import (
    delete_installed_model,
    delete_provider_accounts,
    download_hf_model_file,
    get_local_model_runtime_config,
    get_provider_account,
    get_hf_model_details,
    list_installed_models,
    list_provider_connection_specs,
    list_provider_accounts,
    list_provider_models,
    load_ai_settings,
    save_local_model_runtime_config,
    save_provider_runtime_config,
    save_provider_account,
    search_hf_models,
    set_ai_download_root,
)


def action_load_ai_settings() -> Result:
    return load_ai_settings()


def action_set_ai_download_root(download_root: str) -> Result:
    return set_ai_download_root(download_root)


def action_search_hf_models(query: str, *, limit: int | None = None) -> Result:
    return search_hf_models(query, limit=limit)


def action_get_hf_model_details(repo_id: str) -> Result:
    return get_hf_model_details(repo_id)


def action_list_installed_models() -> Result:
    return list_installed_models()


def action_list_provider_accounts(*, include_secret: bool = False) -> Result:
    return list_provider_accounts(include_secret=include_secret)


def action_list_provider_connection_specs() -> Result:
    return list_provider_connection_specs()


def action_list_provider_models(
    *,
    provider_code: str,
    endpoint_url: str | None = None,
    api_key: str | None = None,
    query: str | None = None,
    free_only: bool = False,
    limit: int | None = None,
) -> Result:
    return list_provider_models(
        provider_code=provider_code,
        endpoint_url=endpoint_url,
        api_key=api_key,
        query=query,
        free_only=free_only,
        limit=limit,
    )


def action_get_provider_account(provider_id: int) -> Result:
    return get_provider_account(provider_id)


def action_get_local_model_runtime_config(record: dict) -> Result:
    return get_local_model_runtime_config(record)


def action_save_local_model_runtime_config(record: dict, config: dict) -> Result:
    return save_local_model_runtime_config(record, config)


def action_save_provider_runtime_config(record: dict, *, reasoning_effort: str = "auto") -> Result:
    return save_provider_runtime_config(record, reasoning_effort=reasoning_effort)


def action_save_provider_account(
    *,
    provider_code: str,
    label: str,
    api_key: str,
    provider_id: int | None = None,
    endpoint_url: str | None = None,
    default_model: str | None = None,
    is_enabled: bool = True,
) -> Result:
    return save_provider_account(
        provider_code=provider_code,
        label=label,
        api_key=api_key,
        provider_id=provider_id,
        endpoint_url=endpoint_url,
        default_model=default_model,
        is_enabled=is_enabled,
    )


def action_delete_provider_accounts(provider_ids: list[int] | tuple[int, ...]) -> Result:
    return delete_provider_accounts(provider_ids)


def action_download_hf_model(
    *,
    repo_id: str,
    filename: str,
    download_root: str | None = None,
    progress_callback=None,
    pause_requested=None,
) -> Result:
    return download_hf_model_file(
        repo_id=repo_id,
        filename=filename,
        download_root=download_root,
        progress_callback=progress_callback,
        pause_requested=pause_requested,
    )


def action_delete_installed_model(model_id: int) -> Result:
    return delete_installed_model(model_id)


def action_export_report_snapshot_xlsx(
    *,
    report_snapshot: dict,
    output_path: str,
) -> Result:
    """Thin AI-domain manual action over the shared Core XLSX writer."""

    return export_report_snapshot_xlsx(
        report_snapshot=dict(report_snapshot or {}),
        output_path=output_path,
    )


def action_save_workflow_spec(*, proposal: dict) -> Result:
    """Canonical local action; shared runtime authorizes the exact proposal."""
    from AI.processors.workflow_store import save_prepared_workflow
    from Feedback.processors.pipeline import map_error_to_message
    try:
        revision = save_prepared_workflow(proposal)
        return Result.ok("İş talimatlarının tam sürümü kaydedildi.", close_dialog=False,
                         data=revision.to_dict())
    except Exception as exc:
        return Result.fail(map_error_to_message(exc), error=exc, close_dialog=False)
