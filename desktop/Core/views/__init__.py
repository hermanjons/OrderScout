from __future__ import annotations

from importlib import import_module
import sys as _sys
from typing import Any


_LAZY_EXPORTS = {
    "AppMessageCenter": ".messaging",
    "SmoothHeightFrame": ".animated_sections",
    "ListLoadingOverlay": ".splitters",
    "ResettableSplitter": ".splitters",
    "SplitterHandleWithReset": ".splitters",
    "ActionPulseButton": ".controls",
    "BadgeButton": ".controls",
    "CircularProgressButton": ".controls",
    "GlowActionButton": ".controls",
    "NumberStepper": ".controls",
    "LabeledActionInput": ".controls",
    "ListSmartItemWidget": ".controls",
    "PackageButton": ".controls",
    "SelectClearToggleButton": ".controls",
    "SwitchButton": ".controls",
    "AnimatedBorderLineEdit": ".inputs",
    "CircularPercentageInput": ".inputs",
    "CurrencyAmountInput": ".inputs",
    "CurrencyPulseLineEdit": ".inputs",
    "NumericPulseLineEdit": ".inputs",
    "NumericRangeGlowInput": ".inputs",
    "PercentageProgressLineEdit": ".inputs",
    "PercentageValueValidator": ".inputs",
    "PhoneNumberInput": ".inputs",
    "FileBadgePicker": ".files",
    "FlowLayout": ".files",
    "DateSelector": ".selectors",
    "SwitchSelectWidget": ".selectors",
    "TimeSelector": ".selectors",
    "ExcelTableWidget": ".tables",
    "GlowBadge": ".tables",
    "optimized_table_updates": ".tables",
    "AnimatedGuidanceRing": ".record_workspace",
    "compose_record_workspace_style": ".record_workspace",
    "EditLockOverlay": ".record_workspace",
    "RECORD_WORKSPACE_STYLE": ".record_workspace",
    "RecordWorkspaceBehaviorAdapter": ".record_workspace",
    "RecordWorkspaceBehaviorController": ".record_workspace",
    "RecordWorkspaceCardRecord": ".record_workspace",
    "RecordWorkspaceEditorActionBar": ".record_workspace",
    "RecordWorkspaceFooterBar": ".record_workspace",
    "RecordWorkspaceListDelegate": ".record_workspace",
    "RecordWorkspaceListModel": ".record_workspace",
    "RecordWorkspaceListWidget": ".record_workspace",
    "RecordWorkspaceScaffold": ".record_workspace",
    "RecordWorkspaceSectionCard": ".record_workspace",
    "RecordWorkspaceSplitShell": ".record_workspace",
    "QuickAccessSection": ".tab_widgets",
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


_sys.modules.setdefault(__name__ + ".views", _sys.modules[__name__])
