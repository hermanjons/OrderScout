"""Model-accessible conversation controls with host-bound state authority."""
from AI.processors.session_state import AgentSessionState
from Feedback.processors.pipeline import Result


def cancel_pending_approval(*, action_id: str, reason: str = "", runtime_context=None) -> Result:
    state = (runtime_context or {}).get("state")
    if not isinstance(state, AgentSessionState):
        return Result.fail("Sohbetin işlem durumu bağlanmadı.", close_dialog=False)
    if not action_id or action_id != state.active_pending_action_id or not state.active_pending_action():
        return Result.fail("İptal hedefi güncel onayla eşleşmiyor.", close_dialog=False,
                           data={"stale_action": True, "effect_executed": False})
    state.cancel_active_pending_action(reason=reason or "user_instruction_via_model", cancelled_by="user_instruction_via_model")
    return Result.ok("Bekleyen işlem iptal edildi; eski onay artık çalıştırılamaz.", close_dialog=False,
                     data={"action_id": action_id, "cancelled": True, "effect_executed": False})
