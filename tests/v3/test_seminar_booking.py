"""Seminar booking policy, persistence and notices; synthetic accounts, no network."""

import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from dududa_v3.features.notify.seminars import SeminarBookingService

ACCOUNT = hashlib.sha256(b"synthetic-seminar-account-a").hexdigest()
OTHER_ACCOUNT = hashlib.sha256(b"synthetic-seminar-account-b").hexdigest()


def report(report_id="R1", **overrides):
    value = {
        "id": report_id,
        "title": "合成学术报告",
        "time": "2030-01-02 15:00",
        "location": "高新校区 B 站直播",
        "available": True,
        "preferred": True,
        "remaining": 3,
    }
    value.update(overrides)
    return value


def snapshot(*reports, selected=(), account=ACCOUNT):
    return {
        "account_key": account,
        "selected_ids": list(selected),
        "reports": list(reports),
        "fetched_at": "2030-01-01T12:00:00+08:00",
        "total": len(reports),
        "available_count": sum(item.get("available") is True for item in reports),
        "recommended_count": sum(item.get("preferred") is True for item in reports),
    }


class SeminarBookingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.services = []
        self.book = AsyncMock(return_value={"status": "booked", "report": report()})
        self.send = AsyncMock(return_value=None)
        self.addCleanup(self.close_services)

    def close_services(self):
        for service in self.services:
            service.close()
        self.services.clear()

    def service(self, *, book=None, send=None):
        service = SeminarBookingService(
            self.root, self.book if book is None else book, self.send if send is None else send
        )
        self.services.append(service)
        return service

    def restart(self, service):
        service.close()
        self.services.remove(service)
        return self.service()

    async def poll(self, service, state, *, enabled=True, preferred_only=True):
        await service.poll(state, enabled=enabled, preferred_only=preferred_only)

    async def test_preference_and_availability_require_explicit_true(self):
        self.book.return_value = {"status": "booked"}
        service = self.service()
        items = [
            report("preferred"),
            report("other-campus", preferred=False),
            report("unknown-preference", preferred=None),
            report("closed", available=False),
            report("unknown-availability", available=None),
            report("truthy-availability", available=1),
            report("truthy-preference", preferred=1),
        ]
        await self.poll(service, snapshot(*items))
        self.assertEqual([call.args[0]["report_id"] for call in self.book.await_args_list], ["preferred"])
        await self.poll(service, snapshot(*items, selected=("preferred",)), preferred_only=False)
        self.assertEqual(
            [call.args[0]["report_id"] for call in self.book.await_args_list],
            ["preferred", "other-campus", "unknown-preference", "truthy-preference"],
        )
        self.assertTrue(all(call.args[0]["preferred_only"] is False for call in self.book.await_args_list[1:]))

    async def test_disabled_poll_observes_selections_without_claiming_available_reports(self):
        service = self.service()
        await self.poll(service, snapshot(report(), selected=("manually-selected",)), enabled=False)
        self.book.assert_not_awaited()
        self.send.assert_not_awaited()
        service = self.restart(service)
        await self.poll(service, snapshot(report("manually-selected"), report()))
        self.assertEqual([call.args[0]["report_id"] for call in self.book.await_args_list], ["R1"])

    async def test_prior_manual_selection_and_withdrawal_never_trigger_booking(self):
        service = self.service()
        await self.poll(service, snapshot(report(), selected=("R1",)))
        service = self.restart(service)
        await self.poll(service, snapshot(report()))
        await self.poll(service, snapshot(report()))
        self.book.assert_not_awaited()
        self.send.assert_not_awaited()

    async def test_worker_detects_manual_selection_without_claiming_auto_success(self):
        self.book.return_value = {"status": "already_selected", "report": report()}
        service = self.service()
        await self.poll(service, snapshot(report()))
        self.assertIn("【学术报告已选中】", self.send.await_args.args[0])
        self.assertNotIn("报名成功", self.send.await_args.args[0])
        service = self.restart(service)
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()
        self.assertIn("不再选中", self.send.await_args.args[0])

    async def test_successful_booking_then_manual_withdrawal_never_reenrolls(self):
        service = self.service()
        await self.poll(service, snapshot(report()))
        await self.poll(service, snapshot(selected=("R1",)))
        self.send.assert_awaited_once()
        service = self.restart(service)
        await self.poll(service, snapshot(report()))
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()
        self.assertEqual(self.send.await_count, 2)
        self.assertIn("【学术报告不再选中】", self.send.await_args.args[0])
        self.assertTrue(all(call.args[0]["operation"] == "seminar_book" for call in self.book.await_args_list))

    async def test_ambiguous_exception_reconciles_read_only_even_when_disabled(self):
        self.book.side_effect = TimeoutError("synthetic-private-response-do-not-display")
        service = self.service()
        await self.poll(service, snapshot(report()))
        self.assertIn("待核实", self.send.await_args.args[0])
        self.assertNotIn("synthetic-private-response", self.send.await_args.args[0])
        service = self.restart(service)
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()
        self.send.assert_awaited_once()
        await self.poll(service, snapshot(selected=("R1",)), enabled=False)
        self.assertIn("【学术报告已选中】", self.send.await_args.args[0])
        self.assertNotIn("报名成功", self.send.await_args.args[0])
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()
        self.assertIn("不再选中", self.send.await_args.args[0])

    async def test_cancelled_inflight_poll_leaves_durable_claim_and_uncertainty_notice(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_book(request):
            entered.set()
            await release.wait()
            return {"status": "booked"}

        self.book.side_effect = blocked_book
        service = self.service()
        task = asyncio.create_task(self.poll(service, snapshot(report())))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        service = self.restart(service)
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()
        self.assertIn("待核实", self.send.await_args.args[0])

    async def test_concurrent_connections_claim_before_network_and_preserve_reconciliation(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_book(request):
            entered.set()
            await release.wait()
            return {"status": "uncertain"}

        self.book.side_effect = blocked_book
        first, second = self.service(), self.service()
        task = asyncio.create_task(self.poll(first, snapshot(report())))
        await entered.wait()
        try:
            await self.poll(second, snapshot(report()))
            self.book.assert_awaited_once()
            await self.poll(second, snapshot(selected=("R1",)), enabled=False)
            await self.poll(second, snapshot(report()), enabled=False)
        finally:
            release.set()
            await task
        await self.poll(first, snapshot(report()))
        self.book.assert_awaited_once()
        self.assertIn("不再选中", self.send.await_args.args[0])
        self.assertEqual(sum("【学术报告报名待核实】" in call.args[0] for call in self.send.await_args_list), 1)

    async def test_concurrent_polls_on_one_service_do_not_duplicate_book_or_notice(self):
        service = self.service()
        # An uncertain result leaves the snapshot applicable to both polls.
        self.book.return_value = {"status": "uncertain"}
        await asyncio.gather(*(self.poll(service, snapshot(report())) for _ in range(3)))
        self.book.assert_awaited_once()
        self.send.assert_awaited_once()

    async def test_failed_notification_restarts_with_same_key_and_no_new_mutation(self):
        delivered_keys = set()
        received = []

        async def send_then_lose_ack(text, key):
            if key not in delivered_keys:
                delivered_keys.add(key)
                received.append(text)
                raise RuntimeError("synthetic-delivery-ack-lost")

        self.send.side_effect = send_then_lose_ack
        service = self.service()
        with self.assertRaisesRegex(RuntimeError, "synthetic-delivery-ack-lost"):
            await self.poll(service, snapshot(report()))
        first_key = self.send.await_args.args[1]
        service = self.restart(service)
        await self.poll(service, snapshot(selected=("R1",)), enabled=False)
        self.assertEqual(self.send.await_args.args[1], first_key)
        self.assertEqual(len(received), 1)
        self.book.assert_awaited_once()
        await self.poll(service, snapshot(selected=("R1",)))
        self.assertEqual(self.send.await_count, 2)

    async def test_unsent_success_is_superseded_after_withdrawal(self):
        self.send.side_effect = RuntimeError("synthetic-notification-offline")
        service = self.service()
        with self.assertRaises(RuntimeError):
            await self.poll(service, snapshot(report()))
        service = self.restart(service)
        self.send.side_effect = None
        await self.poll(service, snapshot(report()), enabled=False)
        text = self.send.await_args.args[0]
        self.assertIn("不再选中", text)
        self.assertNotIn("【学术报告报名成功】", text)
        self.book.assert_awaited_once()

    async def test_rejected_attempt_is_terminal_and_does_not_expose_worker_reason(self):
        self.book.return_value = {
            "status": "rejected", "reason": "<html>synthetic-private-identity</html>",
        }
        service = self.service()
        await self.poll(service, snapshot(report()))
        self.assertIn("未成功", self.send.await_args.args[0])
        self.assertNotIn("synthetic-private-identity", self.send.await_args.args[0])
        service = self.restart(service)
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()
        self.send.assert_awaited_once()

    async def test_unavailable_no_write_outcome_can_be_retried_after_restart(self):
        self.book.return_value = {"status": "unavailable", "reason": "seminar_booking_disabled"}
        service = self.service()
        await self.poll(service, snapshot(report()))
        self.assertIn("未发起报名", self.send.await_args.args[0])
        first_key = self.send.await_args.args[1]
        service = self.restart(service)
        await self.poll(service, snapshot(report()), enabled=False)
        self.book.assert_awaited_once()
        self.book.return_value = {"status": "booked", "report": report()}
        await self.poll(service, snapshot(report()))
        self.assertEqual(self.book.await_count, 2)
        self.assertIn("报名成功", self.send.await_args.args[0])
        self.assertNotEqual(self.send.await_args.args[1], first_key)
        await self.poll(service, snapshot(report()))
        self.assertEqual(self.book.await_count, 2)

    async def test_selected_observation_prevents_retry_after_unavailable(self):
        self.book.return_value = {"status": "unavailable"}
        service = self.service()
        await self.poll(service, snapshot(report()))
        await self.poll(service, snapshot(selected=("R1",)), enabled=False)
        await self.poll(service, snapshot(report()))
        self.book.assert_awaited_once()

    async def test_invalid_worker_results_remain_uncertain_without_retry(self):
        service = self.service()
        results = [None, {}, {"status": []}, {"status": "success"},
                   {"status": "booked", "report": report("wrong-report")}]
        for index, result in enumerate(results):
            with self.subTest(result=result):
                self.book.return_value = result
                item = report(f"invalid-{index}")
                await self.poll(service, snapshot(item))
                self.assertIn("待核实", self.send.await_args.args[0])
                self.assertNotIn("报名成功", self.send.await_args.args[0])
                before = self.book.await_count
                await self.poll(service, snapshot(item))
                self.assertEqual(self.book.await_count, before)

    async def test_account_scoped_claims_and_outbox_do_not_cross_accounts(self):
        self.send.side_effect = RuntimeError("synthetic-offline")
        service = self.service()
        with self.assertRaises(RuntimeError):
            await self.poll(service, snapshot(report()))
        self.send.reset_mock()
        self.send.side_effect = None
        await self.poll(service, snapshot(account=OTHER_ACCOUNT), enabled=False)
        self.send.assert_not_awaited()
        await self.poll(service, snapshot(report(), account=OTHER_ACCOUNT))
        other_key = self.send.await_args.args[1]
        await self.poll(service, snapshot(selected=("R1",)), enabled=False)
        self.assertNotEqual(other_key, self.send.await_args.args[1])
        self.assertEqual(self.book.await_count, 2)
        self.assertEqual({call.args[0]["account_key"] for call in self.book.await_args_list}, {ACCOUNT, OTHER_ACCOUNT})
        for call in self.send.await_args_list:
            self.assertNotIn(ACCOUNT, call.args[0])
            self.assertNotIn(OTHER_ACCOUNT, call.args[0])

    async def test_invalid_or_missing_selected_snapshot_fails_closed(self):
        service = self.service()
        cases = [
            {"account_key": ACCOUNT, "reports": [report()]},
            {**snapshot(report()), "selected_ids": None},
            {**snapshot(report()), "selected_ids": ["R1", "R1"]},
            {**snapshot(report()), "selected_ids": [{}]},
            {**snapshot(report()), "account_key": "synthetic-unhashed-account"},
            snapshot(report(), report()),
        ]
        for invalid in cases:
            with self.subTest(snapshot=invalid), self.assertRaisesRegex(ValueError, "seminar_snapshot_invalid"):
                await self.poll(service, invalid)
        self.book.assert_not_awaited()
        self.send.assert_not_awaited()
