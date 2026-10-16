from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import unittest

from dududa.domain.delivery import DeliveryStatus
from dududa.domain.primitives import Outcome
from dududa.models.contracts import ModelRole, ModelTier
from dududa.rollout import (
    InMemoryRolloutMetrics,
    RolloutFailureKind,
    RolloutLatencyBucket,
    RolloutMetricObservation,
    RolloutMetricStage,
    RolloutMode,
    latency_bucket,
)


class RolloutMetricsTests(unittest.TestCase):
    def test_summary_is_aggregated_bounded_and_contains_no_identity_fields(
        self,
    ) -> None:
        metrics = InMemoryRolloutMetrics(maximum_series=1)
        observation = RolloutMetricObservation(
            1,
            RolloutMode.CANARY,
            RolloutMetricStage.DELIVERY,
            "rollout-v1",
            ModelRole.DIRECT_CHAT,
            ModelTier.HAIKU,
            "endpoint-v1",
            Outcome.RESPONSE,
            DeliveryStatus.SUCCEEDED,
            RolloutFailureKind.NONE,
            latency_bucket(25),
            RolloutLatencyBucket.LE_100_MS,
            1,
            10,
            20,
            Decimal("0.1"),
        )
        metrics.record(observation)
        metrics.record(observation)
        metrics.record(
            RolloutMetricObservation(
                1,
                RolloutMode.SHADOW,
                RolloutMetricStage.SHADOW,
                "rollout-v2",
                None,
                None,
                None,
                Outcome.FAILED,
                None,
                RolloutFailureKind.RUNTIME,
                RolloutLatencyBucket.GT_5_S,
                RolloutLatencyBucket.NOT_RECORDED,
            )
        )

        summary = metrics.summary()

        self.assertEqual(summary.series[0].count, 2)
        self.assertEqual(summary.series[0].input_tokens, 20)
        self.assertEqual(summary.dropped_series, 1)
        serialized = repr(asdict(summary))
        for forbidden in (
            "message_id",
            "group_id",
            "sender_id",
            "raw_message",
            "prompt",
            "provider_body",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_latency_uses_fixed_buckets(self) -> None:
        self.assertIs(latency_bucket(0), RolloutLatencyBucket.LE_10_MS)
        self.assertIs(latency_bucket(5_001), RolloutLatencyBucket.GT_5_S)
        self.assertIs(latency_bucket(None), RolloutLatencyBucket.NOT_RECORDED)


if __name__ == "__main__":
    unittest.main()
