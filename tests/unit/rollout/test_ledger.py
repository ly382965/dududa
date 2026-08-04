from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dududa.domain.delivery import (
    DeliveryPartReceipt,
    DeliveryPartStatus,
    DeliveryReceipt,
    DeliveryStatus,
)
from dududa.domain.primitives import DigestString
from dududa.errors import DududaError
from dududa.rollout import RolloutClaimDisposition, RolloutOwnershipState

from .helpers import NOW, ledger, revision


class SQLiteRolloutLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "rollout.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_two_instances_atomically_claim_one_message(self) -> None:
        first = ledger(self.path)
        second = ledger(self.path)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda store: store.claim(
                        DigestString("message-1"),
                        DigestString("start-1"),
                        "rollout-v1",
                    ),
                    (first, second),
                )
            )

        self.assertEqual(
            {result.disposition for result in results},
            {RolloutClaimDisposition.ACQUIRED, RolloutClaimDisposition.EXISTING},
        )
        self.assertEqual({result.record.revision for result in results}, {1})

    def test_conflict_and_cas_are_fail_closed(self) -> None:
        store = ledger(self.path)
        acquired = store.claim(
            DigestString("message-1"), DigestString("start-1"), "rollout-v1"
        )
        conflict = store.claim(
            DigestString("message-1"), DigestString("start-2"), "rollout-v1"
        )
        self.assertIs(conflict.disposition, RolloutClaimDisposition.CONFLICT)
        started = store.mark_runtime_started(
            acquired.record.message_key_digest, acquired.record.revision
        )
        with self.assertRaises(DududaError):
            store.mark_runtime_started(
                acquired.record.message_key_digest, acquired.record.revision
            )
        self.assertIs(started.state, RolloutOwnershipState.RUNTIME_STARTED)

    def test_delivery_tombstone_survives_restart_and_records_receipt(self) -> None:
        first = ledger(self.path)
        claim = first.claim(
            DigestString("message-1"), DigestString("start-1"), "rollout-v1"
        )
        started = first.mark_runtime_started(
            claim.record.message_key_digest, claim.record.revision
        )
        ready = first.mark_ready_to_send(
            started.message_key_digest,
            started.revision,
            "delivery-1",
            DigestString("request-1"),
        )
        sending = first.begin_delivery(
            ready.message_key_digest,
            "delivery-1",
            DigestString("request-1"),
        )
        self.assertIs(sending.state, RolloutOwnershipState.SEND_STARTED)

        restarted = ledger(self.path)
        recovered = restarted.recover_incomplete()

        self.assertEqual(len(recovered), 1)
        self.assertIs(recovered[0].state, RolloutOwnershipState.UNKNOWN)
        self.assertIs(recovered[0].delivery_status, DeliveryStatus.UNKNOWN)
        replay = restarted.claim(
            DigestString("message-1"), DigestString("start-1"), "rollout-v1"
        )
        self.assertIs(replay.disposition, RolloutClaimDisposition.EXISTING)
        self.assertIs(replay.record.state, RolloutOwnershipState.UNKNOWN)

    def test_known_delivery_status_is_persisted_without_recovery_change(self) -> None:
        store = ledger(self.path)
        claim = store.claim(
            DigestString("message-1"), DigestString("start-1"), "rollout-v1"
        )
        started = store.mark_runtime_started(
            claim.record.message_key_digest, claim.record.revision
        )
        ready = store.mark_ready_to_send(
            started.message_key_digest,
            started.revision,
            "delivery-1",
            DigestString("request-1"),
        )
        store.begin_delivery(
            ready.message_key_digest, "delivery-1", DigestString("request-1")
        )
        receipt = DeliveryReceipt(
            1,
            "delivery-1",
            "run-1",
            DigestString("request-1"),
            "key-1",
            1,
            revision("output"),
            DeliveryStatus.SUCCEEDED,
            (
                DeliveryPartReceipt(
                    1,
                    "part-1",
                    DigestString("content-1"),
                    DeliveryPartStatus.SUCCEEDED,
                    None,
                    None,
                ),
            ),
            NOW + timedelta(seconds=1),
        )
        terminal = store.finish_delivery(ready.message_key_digest, receipt)

        self.assertIs(terminal.state, RolloutOwnershipState.SUCCEEDED)
        self.assertEqual(ledger(self.path).recover_incomplete(), ())
        self.assertIs(
            ledger(self.path).load(ready.message_key_digest).state,
            RolloutOwnershipState.SUCCEEDED,
        )

    def test_delivery_identity_is_unique_across_message_claims(self) -> None:
        store = ledger(self.path)
        records = []
        for suffix in ("1", "2"):
            claim = store.claim(
                DigestString(f"message-{suffix}"),
                DigestString(f"start-{suffix}"),
                "rollout-v1",
            )
            records.append(
                store.mark_runtime_started(
                    claim.record.message_key_digest,
                    claim.record.revision,
                )
            )
        store.mark_ready_to_send(
            records[0].message_key_digest,
            records[0].revision,
            "delivery-shared",
            DigestString("request-shared"),
        )
        with self.assertRaises(DududaError):
            store.mark_ready_to_send(
                records[1].message_key_digest,
                records[1].revision,
                "delivery-shared",
                DigestString("request-other"),
            )


if __name__ == "__main__":
    unittest.main()
