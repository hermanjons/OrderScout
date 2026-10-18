from __future__ import annotations

import hashlib
from typing import Any, Callable

from AI.processors.agent import (
    _answer_claims_unsupported_profit,
    _answer_echoes_user_message,
    _degenerate_repetition_answer,
    _direct_answer_semantically_relevant,
    _should_use_deterministic_answer,
    run_pending_action_read_before_provider,
)
from AI.processors.cloud_runtime import (
    begin_provider_chat_turn,
    provider_invocation_provenance,
    provider_invocation_turn_plan,
)
from AI.processors.model_routing import stable_state_hash
from AI.processors.orders_live_source_recheck_cli import (
    _append_history,
    _compact_text,
    _normalized_visible_answer,
    _runtime_plan,
    _visible_answer_has_mojibake,
)
from AI.processors.session_state import AgentSessionState
from AI.processors.task_runtime import (
    interpret_agent_turn,
    record_conversation_exchange,
    run_agent_task,
    run_existing_observation_read_turn,
    run_model_conversation_turn,
    safe_agent_runtime_context,
)
from AI.processors.turn_service import approval_reply_protocol, run_interpreted_turn, resume_reply_interpretation
from AI.processors.operation_catalog import build_operation_catalog
from AI.processors.tools import available_tools
from Feedback.processors.pipeline import Result


ChatClient = Callable[[str], str]


class _CapturedClient:
    def __init__(self, client: ChatClient) -> None:
        self._client = client
        self.responses: list[dict[str, Any]] = []

    def _invoke(self, contract: str, method: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        prompt = _compact_text(args[0] if args else kwargs.get("prompt"))
        response = _compact_text(method(*args, **kwargs))
        plan = _runtime_plan(self._client)
        provenance = provider_invocation_provenance(plan)
        self.responses.append(
            {
                "call_index": len(self.responses) + 1,
                "contract": contract,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "response": response,
                "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "response_length": len(response),
                "response_received": bool(response),
                "actual_model": _compact_text(
                    provenance.get("final_actual_model")
                    or provenance.get("last_successful_actual_model")
                    or getattr(self._client, "model_name", "")
                ),
                "fallback_used": bool(provenance.get("final_fallback_used")),
            }
        )
        return response

    def __call__(self, prompt: str) -> str:
        return self._invoke("text", self._client, prompt)

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._client, name)
        if name in {"invoke_tools", "invoke_structured", "invoke_json_text"} and callable(attribute):
            return lambda *args, **kwargs: self._invoke(name, attribute, *args, **kwargs)
        return attribute


def _task_tool_evidence(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for step in list(state.get("completed_steps") or []):
        if not isinstance(step, dict):
            continue
        arguments = dict(step.get("arguments") or {})
        result_data = (
            dict(step.get("result_data") or {})
            if isinstance(step.get("result_data"), dict)
            else {}
        )
        step_results = [
            dict(row)
            for row in list(result_data.get("tool_results") or [])
            if isinstance(row, dict)
        ]
        for tool_name in list(step.get("tool_names") or []):
            tool = _compact_text(tool_name)
            if not tool:
                continue
            calls.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "step_id": _compact_text(step.get("step_id")),
                    "decision_source": "task_runtime",
                }
            )
            matching = next(
                (
                    row
                    for row in step_results
                    if _compact_text(row.get("tool")) == tool
                ),
                {},
            )
            payload = (
                dict(matching.get("data") or {})
                if isinstance(matching.get("data"), dict)
                else dict(result_data.get("tool_result") or {})
                if isinstance(result_data.get("tool_result"), dict)
                else result_data
            )
            results.append(
                {
                    "tool": tool,
                    "arguments": arguments,
                    "success": step.get("status") in {"completed", "superseded"},
                    "message": _compact_text(
                        matching.get("message") or step.get("result_message")
                    ),
                    "data": payload,
                    "step_id": _compact_text(step.get("step_id")),
                    "verification_status": _compact_text(
                        step.get("verification_status")
                    ),
                }
            )
    return calls, results


def _runtime_context(
    client: ChatClient,
    *,
    provider_code: str,
    model_name: str,
) -> dict[str, Any]:
    plan = _runtime_plan(client)
    provenance = provider_invocation_provenance(plan)
    return {
        "source": "local" if _compact_text(provider_code).startswith("local") else "cloud",
        "provider_code": _compact_text(provider_code),
        "model_name": _compact_text(
            provenance.get("last_successful_actual_model")
            or getattr(client, "model_name", "")
            or model_name
        ),
        "requested_model": _compact_text(model_name),
        "resource_plan": dict(plan),
    }


def _task_control_evidence(state_payload: dict[str, Any]) -> dict[str, Any]:
    active = (
        dict(state_payload.get("active_entities") or {})
        if isinstance(state_payload.get("active_entities"), dict)
        else {}
    )
    plans: list[dict[str, Any]] = []
    for raw_plan in list(state_payload.get("goal_plans") or []):
        if not isinstance(raw_plan, dict):
            continue
        plans.append(
            {
                "plan_id": _compact_text(raw_plan.get("plan_id")),
                "status": _compact_text(raw_plan.get("status")),
                "source": _compact_text(raw_plan.get("source")),
                "revision": int(raw_plan.get("revision") or 0),
                "steps": [
                    {
                        "step_id": _compact_text(step.get("step_id")),
                        "operation_id": _compact_text(
                            (list(step.get("operation_candidates") or []) or [""])[0]
                        ),
                        "status": _compact_text(step.get("status")),
                        "verification_status": _compact_text(
                            step.get("verification_status")
                        ),
                        "attempt_count": int(step.get("attempt_count") or 0),
                    }
                    for step in list(raw_plan.get("steps") or [])
                    if isinstance(step, dict)
                ],
            }
        )
    return {
        "task_status": _compact_text(state_payload.get("status")),
        "active_goal_plan_id": _compact_text(
            state_payload.get("active_goal_plan_id")
        ),
        "goal_plans": plans,
        "goal_evaluations": [
            dict(row)
            for row in list(active.get("goal_evaluations") or [])
            if isinstance(row, dict)
        ],
        "semantic_verifications": [
            dict(row)
            for row in list(active.get("semantic_verifications") or [])[-12:]
            if isinstance(row, dict)
        ],
        "response_verifications": [
            dict(row)
            for row in list(active.get("response_verifications") or [])[-12:]
            if isinstance(row, dict)
        ],
        "progress_phases": [
            _compact_text(row.get("phase"))
            for row in list(state_payload.get("progress_events") or [])
            if isinstance(row, dict) and _compact_text(row.get("phase"))
        ],
    }


def _final_response_semantically_verified(state_payload: dict[str, Any]) -> bool:
    active = (
        dict(state_payload.get("active_entities") or {})
        if isinstance(state_payload.get("active_entities"), dict)
        else {}
    )
    rows = [
        dict(row)
        for row in list(active.get("response_verifications") or [])
        if isinstance(row, dict)
        and _compact_text(row.get("source")) == "final_response"
    ]
    return bool(rows and rows[-1].get("allowed") is True)


def _final_response_semantic_verification_failed(
    state_payload: dict[str, Any],
) -> bool:
    active = (
        dict(state_payload.get("active_entities") or {})
        if isinstance(state_payload.get("active_entities"), dict)
        else {}
    )
    rows = [
        dict(row)
        for row in list(active.get("response_verifications") or [])
        if isinstance(row, dict)
        and _compact_text(row.get("source")) == "final_response"
    ]
    return bool(rows and rows[-1].get("allowed") is not True)


def _visible_answer_conflicts_with_authoritative_results(
    answer: str,
    tool_results: list[dict[str, Any]],
    state_payload: dict[str, Any],
) -> bool:
    normalized_answer = _normalized_visible_answer(answer)
    literal_message_conflict = bool(tool_results) and any(
        _should_use_deterministic_answer(answer, [row])
        and _normalized_visible_answer(
            _compact_text(row.get("message"))
        ) not in normalized_answer
        for row in tool_results
        if _compact_text(row.get("message"))
    )
    # Tool messages are intentionally terse and may omit a verifier-approved
    # projection such as account/environment scope. Literal containment is a
    # useful fallback for legacy turns, but it must not overrule the typed
    # response verifier that checked the final answer against structured facts.
    return bool(
        literal_message_conflict
        and not _final_response_semantically_verified(state_payload)
    )


def grounded_capability_overview(domain: str) -> tuple[str, dict[str, Any]]:
    """Project user-facing capabilities from the canonical operation catalog."""

    clean_domain = _compact_text(domain).casefold()
    catalog = build_operation_catalog(available_tools(), include_manual=False)
    operation_ids = {
        name
        for name, entry in catalog.items()
        if clean_domain in {"", "general"} or entry.metadata.owner_domain == clean_domain
    }
    groups: list[tuple[set[str], str]] = []
    if clean_domain in {"", "general"}:
        groups = [
            ({"orders.summary", "orders.lookup"}, "Siparişleri, satışları ve iadeleri inceleyip seçtiğin kayıtlarla çalışabilirim."),
            ({"stock.inventory_overview"}, "Stok durumunu ve değerini kayıtlı verilerden inceleyebilirim."),
            ({"finance.cashflow_summary", "finance.cost_item_lookup"}, "Kayıtlı finans hareketlerini ve giderleri para birimine göre inceleyebilirim."),
            ({"listing.summary", "listing.search", "listing.detail_lookup"}, "Ürün ilanlarını ve uygulamadaki bilgilerini inceleyebilirim."),
            ({"web.search", "web.open"}, "İnternette araştırma yapıp sayfaları okuyabilir ve kaynakları karşılaştırabilirim."),
            ({"orders.item_sales_report_xlsx.prepare", "web.research_report_xlsx.prepare", "reports.xlsx.prepare"},
             "Araç sonuçlarından rapor hazırlayıp onayından sonra Excel dosyasını oluşturabilir ve kontrol edebilirim."),
        ]
    elif clean_domain == "orders":
        groups = [
            (
                {"orders.recent", "orders.lookup", "orders.full_context"},
                "Son siparişleri listeleyebilir; sipariş, paket veya takip bilgisiyle arayıp kalem ve iade bağlamını gösterebilirim.",
            ),
            (
                {"orders.ready_to_ship", "orders.ready_to_ship_count"},
                "Kargoya hazır siparişleri doğru mağaza ve ortam kapsamında sayıp listeleyebilirim.",
            ),
            (
                {"orders.summary", "orders.status_counts", "orders.revenue_total"},
                "Dönemsel sipariş, durum ve ciro özeti çıkarıp eşit dönemleri karşılaştırabilirim.",
            ),
            (
                {"orders.fulfillment_risk", "orders.shipping_deadline_analysis"},
                "Gecikme, kargo ve fulfillment risklerini analiz edebilirim.",
            ),
            (
                {"orders.cancellations", "orders.cancelled_count"},
                "İptal edilmiş siparişleri, adetlerini ve mevcutsa iptal nedenlerini analiz edebilirim.",
            ),
            (
                {"returns.query", "returns.reason_summary", "returns.selected_reason_summary"},
                "İadeleri ve onay bekleyen claim'leri inceleyip neden dağılımlarını özetleyebilirim.",
            ),
            (
                {"labels.create_from_orders.prepare", "labels.mark_extracted.prepare"},
                "Exact sipariş kapsamından TANEX etiketi hazırlayabilir ve çıktı durumunu işaretlemeye hazırlayabilirim.",
            ),
            (
                {"orders.change_cargo_provider.prepare", "orders.change_cargo_provider_bulk.prepare"},
                "Tek veya çoklu siparişte kargo firması değişikliğini hazırlayıp açık onayından sonra çalıştırabilirim.",
            ),
            (
                {"returns.approve.prepare"},
                "Exact iade claim'i için onay işlemini dry-run olarak hazırlayabilirim.",
            ),
            (
                {"orders.item_sales_report", "orders.item_sales_report_xlsx.prepare"},
                "En çok satanlar gibi ad-hoc raporlar üretip aynı doğrulanmış snapshot'ı Excel'e hazırlayabilirim.",
            ),
            (
                {"orders.product_public_identities"},
                "Sipariş içeriğini özel müşteri verisi taşımadan web araştırmasına bağlayabilirim.",
            ),
        ]
    included = [
        text
        for required, text in groups
        if required.intersection(operation_ids)
    ]
    if not included:
        included = [
            entry.description
            for entry in catalog.values()
            if entry.metadata.owner_domain == clean_domain
        ][:8]
    answer = (
        ("Kullanılabilir araçlarımla şu işleri yapabilirim:\n- " if clean_domain in {"", "general"}
         else f"{clean_domain.capitalize()} tarafındaki araçlarımla şunları yapabilirim:\n- ")
        + "\n- ".join(included)
    )
    effectful = [
        name
        for name in sorted(operation_ids)
        if catalog[name].metadata.effect_class != "read"
    ]
    if effectful:
        answer += (
            "\n\nDosya, DB veya pazaryeri etkisi olan işleri önce exact kapsamla hazırlarım; "
            "sen açıkça onaylamadan execute etmem ve sonrasında read-back ile doğrularım."
        )
    return answer, {
        "domain": clean_domain,
        "operation_count": len(operation_ids),
        "operation_ids": sorted(operation_ids),
        "effectful_operation_ids": effectful,
        "source": "canonical_operation_catalog",
    }


_POLICY_EXPLANATION_TOPICS = (
    "data_source",
    "freshness",
    "approval",
    "verification",
    "privacy",
    "model_routing",
)


def grounded_policy_explanation_context(
    domain: str,
    topics: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build a secret-free policy context from canonical runtime contracts.

    This is not a capability catalog and it does not answer the user by
    itself.  The typed interpreter selects the relevant policy topics; this
    function supplies only trusted facts that the conversational model may
    explain.  No business read, API request, DB write or file effect occurs.
    """

    clean_domain = _compact_text(domain).casefold() or "general"
    selected_topics = [
        topic
        for topic in dict.fromkeys(
            _compact_text(value).casefold() for value in list(topics or [])
        )
        if topic in _POLICY_EXPLANATION_TOPICS
    ]
    catalog = build_operation_catalog(available_tools(), include_manual=False)
    scoped_entries = {
        name: entry
        for name, entry in catalog.items()
        if clean_domain == "general"
        or entry.metadata.owner_domain == clean_domain
    }
    read_operation_ids = sorted(
        name
        for name, entry in scoped_entries.items()
        if entry.metadata.effect_class == "read"
        and entry.metadata.approval_policy == "none"
    )
    effectful_operation_ids = sorted(
        name
        for name, entry in scoped_entries.items()
        if entry.metadata.effect_class != "read"
    )
    assertions: list[dict[str, str]] = []

    def add(assertion_id: str, topic: str, fact: str) -> None:
        if topic in selected_topics:
            assertions.append(
                {"id": assertion_id, "topic": topic, "fact": fact}
            )

    if clean_domain == "orders":
        add(
            "orders.default_read_source",
            "data_source",
            "Kullanıcı açıkça API senkronizasyonu istemediğinde Orders okuma ve analizleri kalıcı yerel veritabanındaki son kaydedilmiş snapshot üzerinden yapılır.",
        )
        add(
            "orders.no_implicit_marketplace_refresh",
            "data_source",
            "Yerel sipariş okuması pazaryeri API'sini sessizce çağırmaz; API senkronizasyonu ayrı ve açık bir hedeftir.",
        )
        add(
            "orders.local_snapshot_freshness_boundary",
            "freshness",
            "Yerel snapshot uygulamadaki son kalıcı kaydı temsil eder; yeni API senkronizasyonu yapılmadıkça pazaryerinin o saniyedeki durumunu garanti etmez.",
        )
        add(
            "orders.explicit_sync_refresh",
            "freshness",
            "Pazaryeriyle tazelik istenirse agent ayrı senkronizasyon hazırlığı kurar; başarılı execute ve DB read-back sonrasında yeni yerel snapshot kullanılır.",
        )
        add(
            "orders.marketplace_sync_is_not_r0_read",
            "freshness",
            "Pazaryeri API'sinden sipariş çekip yerel snapshot'ı güncelleyen senkronizasyon canonical R0 okuma değildir; kalıcı DB etkisi taşır.",
        )
        add(
            "orders.marketplace_sync_requires_approval",
            "approval",
            "Pazaryeri API'sinden sipariş çekip yerel snapshot'a kaydeden orders.fetch.prepare akışı exact hesap kapsamıyla hazırlanır; açık kullanıcı onayı olmadan execute edilmez ve DB read-back ile doğrulanır.",
        )
    else:
        add(
            "runtime.no_implicit_external_refresh",
            "data_source",
            "Bir domain okuması, kullanıcı hedefi ve typed plan açıkça istemedikçe dış servisi sessizce yenilemez.",
        )
        add(
            "runtime.persisted_source_freshness_boundary",
            "freshness",
            "Kalıcı yerel kaynak dış sistemin o saniyedeki durumuyla aynı kabul edilmez; tazelik ayrı bir senkronizasyon hedefiyle sağlanır.",
        )

    add(
        "runtime.r0_reads_need_no_approval",
        "approval",
        "Canonical R0 read operasyonları salt okunurdur ve kullanıcı onayı gerektirmez.",
    )
    add(
        "runtime.effects_prepare_then_confirm",
        "approval",
        "Dosya, DB veya dış sistem etkisi taşıyan operasyonlar exact kapsamla yalnız prepare edilir; açık kullanıcı onayı gelmeden execute edilmez.",
    )
    add(
        "runtime.approval_is_not_execution",
        "approval",
        "Onay kartının hazırlanması gerçek API, DB, dosya veya yazıcı etkisinin oluştuğu anlamına gelmez.",
    )
    add(
        "runtime.approved_effects_are_verified",
        "approval",
        "Onaylanan etki execute edildikten sonra operasyonun canonical verify/read-back adımı geçmeden işlem tamamlandı diye raporlanmaz.",
    )
    add(
        "runtime.verify_after_execute",
        "verification",
        "Effectful execute sonucu canonical verify/read-back kanıtıyla beklenen exact hedef, kapsam ve çıktı üzerinden doğrulanır.",
    )
    add(
        "runtime.failed_verify_is_not_success",
        "verification",
        "Read-back başarısız veya çelişkiliyse görünür sonuç başarılı/tamamlandı olarak sunulmaz; agent fail-closed durur veya yeniden planlar.",
    )
    add(
        "runtime.private_data_stays_out_of_public_web",
        "privacy",
        "Müşteri, adres, telefon, takip, credential ve özel sipariş verisi public web sorgusuna gönderilmez; gerekiyorsa yalnız privacy-safe public ürün kimliği kullanılır.",
    )
    add(
        "runtime.secret_free_evidence",
        "privacy",
        "API key, secret, token ve parola konuşma kanıtına, artifact'a veya provenance kaydına yazılmaz.",
    )
    add(
        "runtime.explicit_model_provenance",
        "model_routing",
        "Her model çağrısında requested ve actual provider/model provenance'ı tutulur; fallback kullanıldıysa bu açıkça kaydedilir.",
    )
    add(
        "runtime.fallback_obeys_route_policy",
        "model_routing",
        "Fallback yalnız runtime route policy izin veriyorsa uygulanır; exact-model kabul koşularında fallback kapalıdır.",
    )

    payload: dict[str, Any] = {
        "source": "canonical_runtime_policy",
        "domain": clean_domain,
        "topics": selected_topics,
        "assertions": assertions,
        "catalog_evidence": {
            "read_operation_count": len(read_operation_ids),
            "effectful_operation_count": len(effectful_operation_ids),
            "all_read_operations_approval_free": all(
                entry.metadata.approval_policy == "none"
                for entry in scoped_entries.values()
                if entry.metadata.effect_class == "read"
            ),
            "all_effectful_operations_prepare_then_confirm": all(
                entry.metadata.approval_policy == "prepare_then_confirm"
                and entry.metadata.supports_prepare
                for entry in scoped_entries.values()
                if entry.metadata.effect_class != "read"
            ),
            "all_effectful_operations_support_verify": all(
                entry.metadata.supports_verify
                for entry in scoped_entries.values()
                if entry.metadata.effect_class != "read"
            ),
        },
    }
    payload["context_hash"] = stable_state_hash(payload)
    return payload


def policy_context_from_interpretation(
    interpretation: dict[str, Any],
) -> dict[str, Any]:
    if (
        _compact_text(interpretation.get("intent_kind")).casefold()
        != "policy_explanation"
    ):
        return {}
    return grounded_policy_explanation_context(
        _compact_text(interpretation.get("domain")) or "general",
        list(interpretation.get("explanation_topics") or []),
    )


def run_contextual_conversation_turn(
    message: str,
    *,
    client: ChatClient,
    provider_code: str,
    model_name: str,
    db_name: str,
    history: list[dict[str, Any]],
    session_state: AgentSessionState | dict[str, Any] | None = None,
    progress_callback: Callable[..., None] | None = None,
    allow_approval_execute: bool = False,
    task_control: Any = None,
    persist: bool = False,
    task_store_root: str | None = None,
    max_steps: int | None = None,
    max_replans: int | None = None,
    task_created_callback: Callable[[AgentSessionState], None] | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one provider-backed turn through the typed conversation/task control plane.

    This processor is UI-independent. It is used by long acceptance campaigns and is
    intentionally strict: an invalid typed interpretation cannot fall back to the
    legacy regex/business router.
    """

    plan_before_turn = _runtime_plan(client)
    outcome_start = len(
        [
            row
            for row in list(
                plan_before_turn.get("invocation_outcome_history") or []
            )
            if isinstance(row, dict)
        ]
    )
    contract_start = len(
        [
            value
            for value in list(
                plan_before_turn.get("invocation_contract_history") or []
            )
            if _compact_text(value)
        ]
    )
    captured_client = _CapturedClient(client)
    history_count_before = len(history)
    history_hash_before = stable_state_hash({"history": history})
    from AI.processors.model_loop import run_model_loop, project_runtime_result
    if not approval_reply_protocol(message, session_state) and not resume_reply_interpretation(message, session_state):
        begin_provider_chat_turn(client, timeout=getattr(client, "turn_timeout_seconds", 180.0))
        result = run_model_loop(message, client=captured_client, session_state=session_state, history=history,
            db_name=db_name, persist=persist, task_store_root=task_store_root, max_steps=max_steps or 32,
            task_control=task_control, task_created_callback=task_created_callback, progress_callback=progress_callback,
            runtime_context={**_runtime_context(client, provider_code=provider_code, model_name=model_name), **(runtime_context or {})})
        project_runtime_result(result, client, model_name=model_name)
        data = result.data
        answer = data.get("answer") or result.message
        history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": answer}])
        state_payload = data.get("state") or {}
        return {"turn": len(history) // 2, "phase": "model_loop", "success": result.success,
            "application_turn_success": result.success, "mode": data.get("mode"), "answer": answer,
            "objective": message, "decision_path": data.get("decision_path"),
            "turn_interpretation": data.get("turn_interpretation"), "model_invoked": data.get("model_invoked"),
            "tools": data.get("tool_names", []), "tool_arguments": data.get("direct_tool_calls", []),
            "tool_results": data.get("direct_tool_results", []), "session_state": state_payload,
            "session_state_hash": stable_state_hash(state_payload), "approval_required": data.get("approval_required"),
            "action_proposal": data.get("action_proposal"), "runtime_plan": _runtime_plan(client),
            "provider_provenance": provider_invocation_provenance(_runtime_plan(client)),
            "model_responses": captured_client.responses, "response_synthesis": data.get("response_synthesis")}
    pending_read = run_pending_action_read_before_provider(
        message,
        session_state=session_state,
        history=history,
    )
    if pending_read is not None:
        pending_state_payload = dict(
            (pending_read.data or {}).get("session_state")
            or (pending_read.data or {}).get("state")
            or {}
        )
        interpretation_result = Result.ok(
            "Typed pending state read.",
            close_dialog=False,
            data={
                "valid": True,
                "mode": "pending_state_read",
                "domain": _compact_text(
                    pending_state_payload.get("active_domain")
                )
                or "orders",
                "objective": _compact_text(message),
                "intent_kind": "control_state_read",
                "requested_fields": ["scope", "artifact_status"],
                "requires_clarification": False,
                "clarification": "",
                "planner_invoked": False,
            },
        )
    else:
        control_mode = approval_reply_protocol(message, session_state)
        control_interpretation = ({"valid": True, "mode": control_mode, "domain": "general",
                                   "objective": message, "intent_kind": "approval_control", "planner_invoked": False,
                                   "decision_path": "explicit_typed_approval_protocol"} if control_mode else None)
        begin_provider_chat_turn(client, timeout=getattr(client, "turn_timeout_seconds", 180.0))
        resume_interpretation = resume_reply_interpretation(message, session_state)
        interpretation_result = (Result.ok("Typed action control.", data=control_interpretation) if control_interpretation
                                 else Result.ok("Task resume control.", data=resume_interpretation) if resume_interpretation
                                 else interpret_agent_turn(message, planner_client=captured_client, history=history, session_state=session_state))
    interpretation = dict(interpretation_result.data or {})
    mode = _compact_text(interpretation.get("mode")).casefold()
    domain = _compact_text(interpretation.get("domain")).casefold()
    objective = _compact_text(interpretation.get("objective")) or _compact_text(message)
    task_dispatched = False

    def run_headless_task(*args: Any, **kwargs: Any) -> Result:
        nonlocal task_dispatched
        task_dispatched = True
        return run_agent_task(*args, **kwargs)

    result = pending_read
    if result is None:
        result = run_interpreted_turn(
            message,
            interpretation_result=interpretation_result,
            client=captured_client,
            history=history,
            session_state=session_state,
            db_name=db_name,
            runtime_context={**_runtime_context(
                client,
                provider_code=provider_code,
                model_name=model_name,
            ), **(safe_agent_runtime_context(runtime_context) if runtime_context else {})},
            persist=persist,
            task_store_root=task_store_root,
            max_steps=max_steps,
            max_replans=max_replans,
            task_created_callback=task_created_callback,
            progress_callback=progress_callback,
            task_runner=run_headless_task,
            observation_reader=run_existing_observation_read_turn,
            conversation_runner=run_model_conversation_turn,
            capability_reader=grounded_capability_overview,
            policy_context_builder=policy_context_from_interpretation,
            handle_controls=True,
            allow_approval_execute=allow_approval_execute,
            task_control=task_control,
        )

    if result is None and mode == "cancel":
        state = (
            AgentSessionState.from_dict(session_state.to_dict())
            if isinstance(session_state, AgentSessionState)
            else AgentSessionState.from_dict(dict(session_state or {}))
        )
        pending_id = _compact_text(state.active_pending_action_id)
        if pending_id:
            state.cancel_active_pending_action(
                reason="cancelled_from_typed_conversation_runtime",
                cancelled_by="user",
            )
            answer = "Riskli işlem iptal edildi; API, DB veya dosya etkisi oluşmadı."
        else:
            answer = "İptal edilecek aktif bir işlem yok."
        state = record_conversation_exchange(
            session_state=state,
            user_message=message,
            assistant_message=answer,
            mode="cancel",
            objective=objective,
            active_domain=(
                state.active_domain
                if domain in {"", "general"}
                else domain
            ),
        )
        result = Result.ok(
            answer,
            close_dialog=False,
            data={
                "answer": answer,
                "mode": "cancelled",
                "model_invoked": False,
                "decision_path": "typed_pending_action_cancel",
                "state": state.to_dict(),
                "session_state": state.to_dict(),
            },
        )
    elif result is None and mode == "approve" and not allow_approval_execute:
        answer = (
            "Bu kabul kampanyasında gerçek execute kapalı; hazırlanmış işlem çalıştırılmadı."
        )
        state = record_conversation_exchange(
            session_state=session_state,
            user_message=message,
            assistant_message=answer,
            mode="approve_blocked",
            objective=objective,
            active_domain=domain or "orders",
        )
        result = Result.ok(
            answer,
            close_dialog=False,
            data={
                "answer": answer,
                "mode": "approval_blocked",
                "model_invoked": False,
                "decision_path": "acceptance_execute_disabled",
                "state": state.to_dict(),
                "session_state": state.to_dict(),
            },
        )
    elif result is None:
        answer = "Bu hedef için güvenli bir domain görevi oluşturamadım; kapsamı netleştirir misin?"
        state = record_conversation_exchange(
            session_state=session_state,
            user_message=message,
            assistant_message=answer,
            mode="clarify",
            objective=objective,
            active_domain=domain or "general",
        )
        result = Result.ok(
            answer,
            close_dialog=False,
            data={
                "answer": answer,
                "mode": "clarification",
                "model_invoked": True,
                "decision_path": "typed_turn_unhandled_fail_closed",
                "state": state.to_dict(),
                "session_state": state.to_dict(),
            },
        )

    data = dict(result.data or {})
    state_payload = (
        dict(data.get("session_state") or data.get("state") or {})
        if isinstance(data.get("session_state") or data.get("state"), dict)
        else {}
    )
    calls, tool_results = (
        _task_tool_evidence(state_payload)
        if task_dispatched
        else ([], [])
    )
    calls = [
        *[
            dict(row)
            for row in list(data.get("direct_tool_calls") or [])
            if isinstance(row, dict)
        ],
        *calls,
    ]
    tool_results = [
        *[
            dict(row)
            for row in list(data.get("direct_tool_results") or [])
            if isinstance(row, dict)
        ],
        *tool_results,
    ]
    pending = [
        dict(row)
        for row in list(state_payload.get("pending_actions") or [])
        if isinstance(row, dict)
    ]
    answer = _compact_text(data.get("answer") or result.message)
    deterministic_answers = [
        _compact_text(row.get("message"))
        for row in tool_results
        if _compact_text(row.get("message"))
    ]
    visible_conflict = _visible_answer_conflicts_with_authoritative_results(
        answer,
        tool_results,
        state_payload,
    )

    _append_history(
        history,
        user_message=message,
        answer=answer,
        conversation_context={
            "active_domain": _compact_text(state_payload.get("active_domain")),
            "active_selection_ids": dict(state_payload.get("active_selection_ids") or {}),
            "active_pending_action_id": _compact_text(
                state_payload.get("active_pending_action_id")
            ),
        },
    )
    runtime_plan = provider_invocation_turn_plan(
        _runtime_plan(client),
        outcome_start=outcome_start,
        contract_start=contract_start,
    )
    if (
        not runtime_plan.get("invocation_outcome_history")
        and not captured_client.responses
    ):
        # Legacy test/custom clients may expose only a configured model name
        # and no per-call ledger.  When this turn made no provider call, scrub
        # those configuration fields from response provenance.
        runtime_plan.update(
            {
                "actual_model": "",
                "last_successful_actual_model": "",
                "successful_actual_models": [],
                "model_response_count": 0,
                "any_model_response_received": False,
                "final_model_response_received": False,
                "any_model_fallback_used": False,
                "fallback_used": False,
                "model_invocation_attempted": False,
                "invocation_error_reason": "",
                "final_invocation_error_reason": "",
            }
        )
    provider_provenance = provider_invocation_provenance(runtime_plan)
    interpretation_valid = bool(
        interpretation_result.success and interpretation.get("valid")
    )
    task_failed = bool(
        task_dispatched
        and _compact_text(state_payload.get("status")).casefold() == "failed"
    )
    response_verification_failed = _final_response_semantic_verification_failed(
        state_payload
    )
    application_turn_success = bool(
        result.success and not task_failed and not response_verification_failed
    )
    return {
        "turn": len(history) // 2,
        "phase": "typed_control_plane",
        "user": _compact_text(message),
        # A fail-closed clarification can be a successful application response
        # while still being a failed model-evaluation turn. Preserve both facts
        # so acceptance cannot count an invalid typed contract as passing.
        "success": bool(application_turn_success and interpretation_valid),
        "application_turn_success": application_turn_success,
        "mode": _compact_text(data.get("mode")),
        "turn_interpretation": interpretation,
        "objective": objective,
        "decision_path": _compact_text(data.get("decision_path")),
        "provider_unavailable": data.get("provider_unavailable") is True,
        "provider_failure": dict(data.get("provider_failure") or {}),
        "response_semantic_corrections": [
            _compact_text(value)
            for value in list(data.get("response_semantic_corrections") or [])
            if _compact_text(value)
        ],
        "interpretation_model_invoked": bool(
            interpretation.get("planner_invoked")
        ),
        "task_planner_model_invoked": bool(
            task_dispatched
            and data.get("model_invoked")
        ),
        "model_invoked": bool(
            any(
                row.get("response_received") is True
                for row in captured_client.responses
            )
            or (
                runtime_plan.get("invocation_outcome_history")
                and provider_provenance.get("any_model_response_received")
            )
        ),
        "tools": [_compact_text(row.get("tool")) for row in calls],
        "tool_arguments": calls,
        "tool_results": tool_results,
        "answer": answer,
        "answer_length": len(answer),
        "visible_answer_quality": {
            "present": bool(answer),
            "no_mojibake": not _visible_answer_has_mojibake(answer),
            "not_user_echo": not _answer_echoes_user_message(message, answer),
            "not_degenerate_repetition": not _degenerate_repetition_answer(answer),
            "semantically_relevant": _direct_answer_semantically_relevant(message, answer),
        },
        "visible_answer_conflicts_with_tool_data": visible_conflict,
        "unsupported_profit_claim": _answer_claims_unsupported_profit(answer),
        "approval_required": bool(pending),
        "action_proposal": pending[0] if pending else {},
        "session_state": state_payload,
        "session_state_hash": stable_state_hash(state_payload),
        "task_control_evidence": _task_control_evidence(state_payload),
        "history_message_count_before_turn": history_count_before,
        "history_message_count_after_turn": len(history),
        "history_state_hash_before_turn": history_hash_before,
        "history_state_hash_after_turn": stable_state_hash({"history": history}),
        "runtime_plan": runtime_plan,
        "provider_provenance": provider_provenance,
        "model_responses": list(captured_client.responses),
        "authoritative_result_messages": deterministic_answers,
    }
