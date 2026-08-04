from __future__ import annotations

from dataclasses import replace
import unittest

from dududa.domain.message import AttachmentKind, AttachmentRef
from dududa.errors import DududaError
from dududa.rollout import (
    RolloutAdmissionAction,
    RolloutMode,
    decide_rollout_admission,
    parse_rollout_control_config,
)

from .helpers import connector, control


def raw_config(mode: str = "off") -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": mode,
        "revision": "rollout-v1",
        "delivery_enabled": False,
        "allowlisted_group_ids": ["g-1"],
        "kill_switch": False,
        "tools_enabled": False,
        "memory_enabled": False,
        "maximum_text_bytes": 1_024,
        "shadow_max_in_flight": 2,
        "shadow_timeout_ms": 1_000,
        "canary_timeout_ms": 5_000,
    }


class RolloutConfigAndAdmissionTests(unittest.TestCase):
    def test_all_modes_parse_strictly_and_freeze_allowlist(self) -> None:
        for mode in RolloutMode:
            with self.subTest(mode=mode):
                parsed = parse_rollout_control_config(raw_config(mode.value))
                self.assertIs(parsed.mode, mode)
                self.assertEqual(parsed.allowlisted_group_ids, frozenset({"g-1"}))

    def test_invalid_or_ambiguous_configuration_is_rejected(self) -> None:
        cases = []
        unknown = raw_config()
        unknown["extra"] = True
        cases.append(unknown)
        wrong_bool = raw_config()
        wrong_bool["kill_switch"] = "false"
        cases.append(wrong_bool)
        wrong_groups = raw_config()
        wrong_groups["allowlisted_group_ids"] = "g-1"
        cases.append(wrong_groups)
        bad_mode = raw_config("random")
        cases.append(bad_mode)
        empty_revision = raw_config()
        empty_revision["revision"] = ""
        cases.append(empty_revision)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises((DududaError, TypeError)):
                    parse_rollout_control_config(value)

    def test_admission_matrix_is_deterministic_and_structural(self) -> None:
        attachment = AttachmentRef(
            "a-1", AttachmentKind.IMAGE, "image/png", 1, None, None
        )
        cases = (
            (control(RolloutMode.OFF), connector(), RolloutAdmissionAction.LEGACY),
            (
                control(RolloutMode.SHADOW),
                connector(),
                RolloutAdmissionAction.SHADOW,
            ),
            (control(), connector(), RolloutAdmissionAction.CANARY),
            (
                control(allowlisted_group_ids=frozenset({"other"})),
                connector(),
                RolloutAdmissionAction.LEGACY,
            ),
            (control(), connector(mentioned_user=None), RolloutAdmissionAction.LEGACY),
            (
                control(),
                connector(mentioned_user="other-bot", text="@bot-1 hello"),
                RolloutAdmissionAction.LEGACY,
            ),
            (
                control(),
                connector(group_id=None),
                RolloutAdmissionAction.LEGACY,
            ),
            (control(), connector(text=" "), RolloutAdmissionAction.LEGACY),
            (
                control(maximum_text_bytes=4),
                connector(text="你好"),
                RolloutAdmissionAction.LEGACY,
            ),
            (
                control(),
                connector(attachments=(attachment,)),
                RolloutAdmissionAction.LEGACY,
            ),
            (control(tools_enabled=True), connector(), RolloutAdmissionAction.LEGACY),
            (
                control(memory_enabled=True),
                connector(),
                RolloutAdmissionAction.LEGACY,
            ),
            (control(kill_switch=True), connector(), RolloutAdmissionAction.LEGACY),
            (
                control(delivery_enabled=False),
                connector(),
                RolloutAdmissionAction.LEGACY,
            ),
        )
        for config, value, expected in cases:
            with self.subTest(config=config, value=value):
                self.assertIs(decide_rollout_admission(value, config).action, expected)

    def test_shadow_does_not_depend_on_delivery_enable(self) -> None:
        decision = decide_rollout_admission(
            connector(),
            replace(control(RolloutMode.SHADOW), delivery_enabled=False),
        )
        self.assertIs(decision.action, RolloutAdmissionAction.SHADOW)


if __name__ == "__main__":
    unittest.main()
