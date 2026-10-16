from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs

import httpx
from astrbot_plugin_dududa_notify.assignment_client import (
    APP_PATH,
    FILE_PATH,
    ORIGIN,
    HomeworkClient,
    HomeworkError,
    text_from_file,
)
from astrbot_plugin_dududa_notify.homework import (
    CHINA_TIME,
    HomeworkService,
    is_quiz,
    render_markdown,
)

from tests.test_private_notifications import RECIPIENT, load_plugin


def assignment(number=1, **changes):
    return {
        "id": f"assignment-{number}",
        "course": "Test Course",
        "title": f"Exercise {number}",
        "description": "Answer five questions. Keep a real dialogue record.",
        "deadline": "2026-10-01 12:00:00",
        "requirements_token": "",
        "submission_token": "",
        "submission_id": "",
        "submitted": False,
        "can_edit": True,
        "attachments": [],
        "upload_types": ["zip", "pdf"],
        **changes,
    }


class School:
    def __init__(self):
        self.requests = []
        self.row = {
            "WID": "assignment-1",
            "XH": "student-test",
            "KCMC": "Test Course",
            "ZYMC": "Exercise 1",
            "ZYSM": "Answer five questions. Keep a real dialogue record.",
            "ZYJZSJ": "2026-10-01 12:00:00",
            "ZY": "",
            "XSZYWID": "",
        }
        self.pages = [[{"WID": "assignment-1"}]]
        self.total = 1
        self.can_edit = True
        self.accept_receipt = True
        self.receipt_owner = "student-test"

    def handle(self, request):
        self.requests.append(request)
        path = request.url.path
        data = (
            {
                key: values[0]
                for key, values in parse_qs(
                    request.content.decode(), keep_blank_values=True
                ).items()
            }
            if "multipart" not in request.headers.get("content-type", "")
            else {}
        )
        if request.method == "GET" and path.endswith("index.do"):
            return httpx.Response(
                200, text='var pageMeta = {"params":{"USERID":"student-test"}};'
            )
        if path.endswith("/modules/wdzy.do"):
            assert data == {"*json": "1"}
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "wdzycx_form",
                            "controls": [
                                {
                                    "name": "ZY",
                                    "form.JSONParam": "{'type': ['zip', 'pdf']}",
                                }
                            ],
                        }
                    ]
                },
            )
        if path.endswith("/wdzycx.do"):
            assert data["XH"] == "student-test"
            page = int(data["pageNumber"])
            rows = self.pages[page - 1] if page <= len(self.pages) else []
            return httpx.Response(
                200, json={"datas": {"wdzycx": {"rows": rows, "totalSize": self.total}}}
            )
        if path.endswith("/wdzycx_form.do"):
            assert data["XH"] == "student-test"
            return httpx.Response(
                200, json={"datas": {"wdzycx_form": {"rows": [self.row]}}}
            )
        if path.endswith("/validateCanEdit.do"):
            return httpx.Response(200, json={"success": True, "canEdit": self.can_edit})
        if path.endswith("/uploadTempFile.do") or "/saveAttachment/" in path:
            return httpx.Response(200, json={"success": True})
        if path.endswith("/sczy.do"):
            if self.accept_receipt:
                self.row.update(
                    ZY=data["ZY"], XSZYWID="submission-1", XH=self.receipt_owner
                )
            return httpx.Response(200, json={"datas": {"sczy": {"code": 1}}})
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    def writes(self):
        return [
            request
            for request in self.requests
            if any(
                value in request.url.path
                for value in ("uploadTempFile", "saveAttachment", "sczy.do")
            )
        ]


class HomeworkClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.school = School()
        self.http = httpx.AsyncClient(
            base_url=ORIGIN, transport=httpx.MockTransport(self.school.handle)
        )
        self.addAsyncCleanup(self.http.aclose)
        self.client = HomeworkClient(self.http)
        await self.client.initialize()

    async def test_authenticated_read_and_complete_pagination(self):
        self.school.pages = [[{"WID": "assignment-1"}], [{"WID": "assignment-2"}]]
        self.school.total = 2
        self.assertEqual(len(await self.client.list_rows()), 2)
        item = await self.client.detail("assignment-1")
        self.assertEqual(item["description"], assignment()["description"])
        self.assertEqual(item["upload_types"], ["zip", "pdf"])
        self.assertFalse(self.school.writes())

    async def test_snapshot_verifies_submitted_details_instead_of_omitting_counts(self):
        self.school.row["ZY"] = "uploaded-answer-token"
        result = await self.client.snapshot()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["assignments"], [])
        self.assertEqual(len(result["submitted_assignments"]), 1)
        self.assertTrue(result["submitted_assignments"][0]["submitted"])
        self.assertFalse(self.school.writes())

    async def test_snapshot_does_not_trust_list_submission_flag_over_detail(self):
        self.school.pages = [[{"WID": "assignment-1", "ZY": "stale-list-token"}]]
        result = await self.client.snapshot()
        self.assertEqual(len(result["assignments"]), 1)
        self.assertEqual(result["submitted_assignments"], [])

    async def test_business_error_with_empty_rows_is_not_an_empty_success(self):
        async with httpx.AsyncClient(
            base_url=ORIGIN,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "code": "-1",
                        "datas": {"wdzycx": {"rows": [], "totalSize": 0}},
                    },
                )
            ),
        ) as session:
            client = HomeworkClient(session)
            client.student_id = "student-test"
            with self.assertRaisesRegex(HomeworkError, "request_rejected"):
                await client.list_rows()

    async def test_incomplete_or_repeated_page_is_not_empty_success(self):
        self.school.total = 2
        with self.assertRaisesRegex(HomeworkError, "incomplete"):
            await self.client.list_rows()
        self.school.pages.append(self.school.pages[0])
        with self.assertRaisesRegex(HomeworkError, "repeated_page"):
            await self.client.list_rows()

    async def test_wrong_student_never_reaches_edit_or_upload(self):
        self.school.row["XH"] = "different-student"
        with self.assertRaisesRegex(HomeworkError, "owner_mismatch"):
            await self.client.submit(
                assignment(), "answer.zip", b"reviewed", "a" * 32 + "1"
            )
        self.assertFalse(self.school.writes())
        self.assertFalse(
            any(
                "validateCanEdit" in request.url.path
                for request in self.school.requests
            )
        )

    async def test_preconditions_do_not_upload(self):
        cases = [
            ({"ZY": "existing"}, True, "answer.zip", "already_submitted"),
            ({"ZYSM": "changed"}, True, "answer.zip", "requirements_changed"),
            ({}, False, "answer.zip", "submission_closed"),
            ({}, True, "answer.md", "file_type_rejected"),
        ]
        original = self.school.row.copy()
        for changes, can_edit, filename, error in cases:
            with self.subTest(error=error):
                self.school.row = {**original, **changes}
                self.school.can_edit = can_edit
                with self.assertRaisesRegex(HomeworkError, error):
                    await self.client.submit(
                        assignment(), filename, b"reviewed", "a" * 32 + "1"
                    )
                self.assertFalse(self.school.writes())

    async def test_submission_uses_official_form_and_checks_receipt(self):
        token = "a" * 32 + "1"
        result = await self.client.submit(
            assignment(), "answer.zip", b"reviewed-archive", token
        )
        self.assertEqual(
            result, {"status": "submitted", "submission_id": "submission-1"}
        )
        upload, save, submit = self.school.writes()
        self.assertEqual(upload.url.path, FILE_PATH + "/uploadTempFile.do")
        self.assertIn(b'name="files[]"; filename="answer.zip"', upload.content)
        self.assertIn(b"reviewed-archive", upload.content)
        self.assertEqual(
            save.url.path, FILE_PATH + f"/saveAttachment/{token[:-1]}/{token}.do"
        )
        self.assertEqual(submit.url.path, APP_PATH + "/modules/wdzy/sczy.do")
        self.assertEqual(
            parse_qs(submit.content.decode(), keep_blank_values=True),
            {
                "WID": [""],
                "ZYWID": ["assignment-1"],
                "XH": ["student-test"],
                "ZY": [token],
                "CJ": ["99"],
            },
        )
        await self.client.submit(assignment(), "answer.zip", b"reviewed-archive", token)
        self.assertEqual(len(self.school.writes()), 3)

    async def test_success_code_without_persisted_token_is_not_success(self):
        self.school.accept_receipt = False
        with self.assertRaisesRegex(HomeworkError, "submission_unconfirmed"):
            await self.client.submit(
                assignment(), "answer.zip", b"reviewed", "a" * 32 + "1"
            )

    async def test_pdf_is_uploaded_with_pdf_content_type(self):
        await self.client.submit(
            assignment(), "answer.pdf", b"%PDF-reviewed", "a" * 32 + "1"
        )
        upload = self.school.writes()[0]
        self.assertIn(b"Content-Type: application/pdf", upload.content)
        self.assertIn(b"%PDF-reviewed", upload.content)

    async def test_receipt_identity_failure_is_uncertain_not_a_preupload_error(self):
        self.school.receipt_owner = "unexpected-student"
        with self.assertRaisesRegex(HomeworkError, "submission_unconfirmed"):
            await self.client.submit(
                assignment(), "answer.zip", b"reviewed", "a" * 32 + "1"
            )
        self.assertEqual(len(self.school.writes()), 3)

    def test_zip_does_not_silently_omit_unreadable_material(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("instructions.txt", "Read the image too")
            archive.writestr("question.png", b"image content")
        self.assertEqual(text_from_file("materials.zip", buffer.getvalue()), "")
        self.assertEqual(text_from_file("instructions.txt", b"question"), "question")


class HomeworkWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        clock = patch(
            "astrbot_plugin_dududa_notify.homework.current_time",
            return_value=datetime(2026, 9, 24, 10, tzinfo=CHINA_TIME),
        )
        clock.start()
        self.addCleanup(clock.stop)
        self.query = AsyncMock(return_value={"assignments": [assignment()]})
        self.generate = AsyncMock(
            return_value=("## Answer\nAn actual model response.", "test-model")
        )
        self.text = AsyncMock()
        self.file = AsyncMock()
        self.pdf = AsyncMock(
            side_effect=lambda content: b"%PDF-1.4\n" + content.encode()
        )
        self.service = HomeworkService(
            self.directory.name,
            RECIPIENT,
            self.query,
            self.generate,
            self.text,
            self.file,
            render_pdf=self.pdf,
        )
        self.addCleanup(lambda: self.service.close())

    async def test_cold_start_lists_all_pending_without_submitting(self):
        self.query.return_value = {"assignments": [assignment(1), assignment(2)]}
        await self.service.poll(startup=True)
        summary = self.text.await_args_list[0].args[0]
        self.assertIn("未完成作业：2 份", summary)
        self.assertIn("H1", summary)
        self.assertIn("H2", summary)
        self.assertEqual(self.file.await_count, 2)
        self.assertEqual(
            [call.args[0]["operation"] for call in self.query.await_args_list], ["list"]
        )
        self.text.reset_mock()
        await self.service.poll()
        self.text.assert_not_awaited()
        self.assertEqual(self.generate.await_count, 2)
        self.service.close()
        self.service = HomeworkService(
            self.directory.name,
            RECIPIENT,
            self.query,
            self.generate,
            self.text,
            self.file,
            render_pdf=self.pdf,
        )
        await self.service.poll(startup=True)
        self.assertIn("未完成作业：2 份", self.text.await_args.args[0])
        self.assertEqual(self.generate.await_count, 2)

    async def test_verified_zero_is_scoped_and_not_resent_after_reload(self):
        self.query.return_value = {
            "total": 1,
            "assignments": [],
            "submitted_assignments": [assignment(submitted=True)],
        }
        await self.service.poll(startup=True)
        text = self.text.await_args.args[0]
        self.assertIn("【研究生系统作业】", text)
        self.assertIn("不含 BB", text)
        self.assertIn("已核实已提交：1 份", text)
        self.assertIn("核验时间", text)
        self.assertEqual(self.service.get(1)["active"], 0)
        self.assertTrue(json.loads(self.service.get(1)["payload"])["submitted"])
        self.generate.assert_not_awaited()
        self.service.close()
        self.service = HomeworkService(
            self.directory.name,
            RECIPIENT,
            self.query,
            self.generate,
            self.text,
            self.file,
            render_pdf=self.pdf,
        )
        await self.service.poll(startup=True)
        self.text.assert_awaited_once()

    async def test_incomplete_zero_snapshot_keeps_existing_assignments(self):
        self.service.sync([assignment()])
        self.query.return_value = {
            "total": 1,
            "assignments": [],
            "submitted_assignments": [],
        }
        with self.assertRaisesRegex(ValueError, "homework_snapshot_incomplete"):
            await self.service.poll(startup=True)
        self.assertEqual(self.service.get(1)["active"], 1)
        self.text.assert_not_awaited()

    async def test_failed_query_never_clears_last_successful_list(self):
        self.service.sync([assignment()])
        self.query.side_effect = ValueError("campus_database_login_unavailable")
        with self.assertRaises(ValueError):
            await self.service.poll(startup=True)
        self.assertEqual(self.service.get(1)["active"], 1)
        self.text.assert_not_awaited()

    async def test_records_real_prompt_answer_time_and_blank_comment(self):
        await self.service.poll(startup=True)
        draft = self.service.latest(1)
        record = json.loads(draft["records"])[0]
        self.assertEqual(record["question"], self.generate.await_args.args[1])
        self.assertEqual(record["answer"], self.generate.return_value[0])
        self.assertLessEqual(
            datetime.fromisoformat(record["asked_at"]),
            datetime.fromisoformat(record["answered_at"]),
        )
        self.assertEqual(record["comment"], "")
        self.assertIn("（待本人填写）", draft["content"])
        self.assertEqual(self.file.await_args.args[0].read_bytes(), draft["archive"])
        self.assertTrue(draft["filename"].endswith(".pdf"))
        self.assertTrue(draft["archive"].startswith(b"%PDF-"))
        self.pdf.assert_awaited_once_with(draft["content"])

    async def test_comments_create_new_version_without_fake_model_call(self):
        await self.service.poll(startup=True)
        await self.service.command("评论 H1 1 My own assessment")
        draft = self.service.latest(1)
        self.assertEqual(draft["version"], 2)
        self.assertEqual(
            json.loads(draft["records"])[0]["comment"], "My own assessment"
        )
        self.generate.assert_awaited_once()
        with self.assertRaisesRegex(ValueError, "最新版本"):
            await self.service.command("确认 H1 v1")
        self.query.assert_awaited_once()

    async def test_revision_without_initial_draft_and_changed_requirements(self):
        self.service.sync([assignment()])
        await self.service.command("改稿 H1 Focus on question two")
        self.assertIn("Focus on question two", self.generate.await_args.args[1])
        self.query.return_value = {
            "assignments": [assignment(description="Updated requirement")]
        }
        await self.service.poll()
        self.assertEqual(self.service.latest(1)["version"], 2)
        self.assertIn("Updated requirement", self.generate.await_args.args[1])
        with self.assertRaisesRegex(ValueError, "最新版本"):
            await self.service.command("确认 H1 v1")

    async def test_exact_confirmation_sends_reviewed_bytes_once(self):
        await self.service.poll(startup=True)
        reviewed = self.file.await_args.args[0].read_bytes()
        await self.service.command("确认 H1")
        self.query.assert_awaited_once()
        self.query.return_value = {"status": "submitted", "submission_id": "receipt"}
        result = await self.service.command("确认 H1 v1")
        self.assertIn("已提交", result)
        submission = self.query.await_args.args[0]
        self.assertEqual(submission["operation"], "submit")
        self.assertEqual(base64.b64decode(submission["content"]), reviewed)
        await self.service.command("确认 H1 v1")
        self.assertEqual(self.query.await_count, 2)
        self.assertIn("未完成作业：0 份", self.service.listing())

    async def test_file_delivery_failure_does_not_block_other_assignments(self):
        self.query.return_value = {"assignments": [assignment(1), assignment(2)]}
        self.file.side_effect = [RuntimeError("offline"), None, None]
        await self.service.poll(startup=True)
        self.assertFalse(self.service.latest(1)["delivered"])
        self.assertTrue(self.service.latest(2)["delivered"])
        with self.assertRaisesRegex(ValueError, "先查看"):
            await self.service.command("确认 H1 v1")
        await self.service.poll()
        self.assertTrue(self.service.latest(1)["delivered"])

    async def test_uncertain_submission_never_automatically_reuploads(self):
        await self.service.poll(startup=True)
        self.query.side_effect = TimeoutError("lost response")
        with self.assertRaises(TimeoutError):
            await self.service.command("确认 H1 v1")
        draft = self.service.latest(1)
        self.assertEqual(draft["state"], "uncertain")
        self.query.side_effect = None
        self.query.return_value = {"submission_token": ""}
        with self.assertRaisesRegex(ValueError, "停止重复上传"):
            await self.service.command("确认 H1 v1")
        self.assertEqual(self.query.await_args.args[0]["operation"], "detail")
        self.query.return_value = {
            "submission_token": draft["submission_token"],
            "submission_id": "receipt",
        }
        await self.service.command("确认 H1 v1")
        self.assertEqual(self.service.latest(1)["state"], "submitted")
        self.assertIn("未完成作业：0 份", self.service.listing())
        self.assertEqual(
            sum(
                call.args[0]["operation"] == "submit"
                for call in self.query.await_args_list
            ),
            1,
        )

    async def test_known_preupload_rejection_does_not_leave_uncertain_state(self):
        await self.service.poll(startup=True)
        self.query.side_effect = ValueError("homework_submission_closed")
        with self.assertRaisesRegex(ValueError, "submission_closed"):
            await self.service.command("确认 H1 v1")
        self.assertEqual(self.service.latest(1)["state"], "draft")

    async def test_unreadable_attachment_requires_human_input(self):
        self.query.return_value = {
            "assignments": [
                assignment(
                    attachments=[
                        {"name": "question.png", "text": "", "readable": False}
                    ]
                )
            ]
        }
        await self.service.poll(startup=True)
        self.generate.assert_not_awaited()
        self.file.assert_not_awaited()
        self.assertIn("附件需要人工阅读", self.text.await_args.args[0])

    async def test_login_failure_before_upload_can_be_retried_after_recovery(self):
        await self.service.poll(startup=True)
        self.query.side_effect = ValueError("cas_ticket_missing")
        with self.assertRaisesRegex(ValueError, "cas_ticket_missing"):
            await self.service.command("确认 H1 v1")
        self.assertEqual(self.service.latest(1)["state"], "draft")
        self.query.side_effect = None
        self.query.return_value = {"status": "submitted", "submission_id": "receipt"}
        await self.service.command("确认 H1 v1")
        self.assertEqual(self.service.latest(1)["state"], "submitted")

    async def test_database_failure_during_login_can_retry_before_any_write(self):
        await self.service.poll(startup=True)
        self.query.side_effect = ValueError("campus_database_login_unavailable")
        with self.assertRaisesRegex(ValueError, "campus_database_login_unavailable"):
            await self.service.command("确认 H1 v1")
        self.assertEqual(self.service.latest(1)["state"], "draft")

    async def test_database_failure_after_login_stays_uncertain_without_reupload(self):
        await self.service.poll(startup=True)
        self.query.side_effect = ValueError("campus_database_unavailable")
        with self.assertRaisesRegex(ValueError, "campus_database_unavailable"):
            await self.service.command("确认 H1 v1")
        self.assertEqual(self.service.latest(1)["state"], "uncertain")
        self.query.reset_mock()
        with self.assertRaises(ValueError):
            await self.service.command("确认 H1 v1")
        self.assertEqual(self.query.await_args.args[0]["operation"], "detail")

    async def test_quiz_is_concise_and_pdf_has_only_current_answer(self):
        self.query.return_value = {
            "assignments": [
                assignment(title="课堂练习9.24", description="解释梯度下降。")
            ]
        }
        await self.service.poll()
        draft = self.service.latest(1)
        self.assertIn("作答方式：小测简答", self.generate.await_args.args[1])
        self.assertIn("不超过150字", self.generate.await_args.args[1])
        self.assertIn(self.generate.return_value[0], draft["content"])
        self.assertNotIn("模型系统提示", draft["content"])
        self.assertNotIn("提问时间", draft["content"])
        self.assertNotIn("待本人填写", draft["content"])
        self.assertTrue(is_quiz(assignment(title="随堂测验")))
        self.assertFalse(is_quiz(assignment(title="搜索算法的实现")))

    async def test_existing_zip_gets_new_pdf_version_without_mutating_reviewed_bytes(
        self,
    ):
        await self.service.poll()
        with self.service.db:
            self.service.db.execute(
                "UPDATE drafts SET filename='old.zip',archive=? WHERE assignment=1",
                (b"old-reviewed-zip",),
            )
        await self.service.poll()
        self.assertEqual(self.service.latest(1)["version"], 2)
        self.assertTrue(self.service.latest(1)["filename"].endswith(".pdf"))
        old = self.service.db.execute(
            "SELECT archive FROM drafts WHERE assignment=1 AND version=1"
        ).fetchone()
        self.assertEqual(old[0], b"old-reviewed-zip")
        self.generate.assert_awaited_once()

    async def test_expired_assignments_are_listed_but_not_generated(self):
        self.query.return_value = {
            "assignments": [assignment(deadline="2000-01-01 00:00:00")]
        }
        await self.service.poll(startup=True)
        self.assertIn("未完成作业：1 份", self.text.await_args.args[0])
        self.generate.assert_not_awaited()


class HomeworkDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = datetime(2026, 9, 24, 10, tzinfo=CHINA_TIME)
        clock = patch(
            "astrbot_plugin_dududa_notify.homework.current_time",
            side_effect=lambda: self.now,
        )
        clock.start()
        self.addCleanup(clock.stop)
        self.item = assignment(
            title="课堂小测",
            description="解释梯度下降。",
            deadline="2026-09-24 10:03:00",
        )
        self.query = AsyncMock(side_effect=self.respond)
        self.generate = AsyncMock(return_value=("简短答案。", "test-model"))
        self.text, self.file = AsyncMock(), AsyncMock()
        self.pdf = AsyncMock(return_value=b"%PDF-1.4\nanswer")
        self.service = HomeworkService(
            self.directory.name,
            RECIPIENT,
            self.query,
            self.generate,
            self.text,
            self.file,
            render_pdf=self.pdf,
            auto_submit=True,
        )
        self.addCleanup(lambda: self.service.close())
        self.service.sync([self.item])

    async def respond(self, request):
        if request["operation"] == "list":
            return {"assignments": [self.item]}
        if request["operation"] == "detail":
            return self.item.copy()
        if request["operation"] == "submit":
            return {"status": "submitted", "submission_id": "receipt"}
        raise AssertionError(request["operation"])

    def submissions(self):
        return [
            call.args[0]
            for call in self.query.await_args_list
            if call.args[0]["operation"] == "submit"
        ]

    async def test_exact_three_minute_boundary_submits_latest_pdf_once(self):
        await self.service.check_deadlines()
        draft = self.service.latest(1)
        self.assertEqual(draft["state"], "submitted")
        self.assertEqual(len(self.submissions()), 1)
        self.assertEqual(
            base64.b64decode(self.submissions()[0]["content"]), draft["archive"]
        )
        self.assertTrue(self.submissions()[0]["filename"].endswith(".pdf"))
        await self.service.check_deadlines()
        self.assertEqual(len(self.submissions()), 1)
        self.assertTrue(
            any(
                "已按你的设置自动提交 PDF" in call.args[0]
                for call in self.text.await_args_list
            )
        )

    async def test_disabled_early_expired_or_unknown_deadline_never_submits(self):
        self.service.auto_submit = False
        await self.service.check_deadlines()
        self.service.auto_submit = True
        for deadline in (
            "2026-09-24 10:03:01",
            "2026-09-24 10:00:00",
            "2026-09-24 09:59:00",
            "unknown",
            None,
        ):
            with self.subTest(deadline=deadline):
                self.service.sync([{**self.item, "deadline": deadline}])
                await self.service.check_deadlines()
        self.query.assert_not_awaited()
        self.generate.assert_not_awaited()

    async def test_school_submission_or_closed_window_is_not_overwritten(self):
        for updates in (
            {"submitted": True, "submission_token": "user-upload"},
            {"can_edit": False},
            {"description": "New requirements"},
            {"deadline": "2026-09-25 10:00:00"},
        ):
            self.service.sync([self.item])
            self.service.deadline_checks.clear()
            self.query.side_effect = None
            self.query.return_value = {**self.item, **updates}
            await self.service.check_deadlines()
        self.assertFalse(self.submissions())
        self.generate.assert_not_awaited()

    async def test_uncertain_result_survives_restart_and_only_reads_for_reconciliation(
        self,
    ):
        async def uncertain(request):
            if request["operation"] == "submit":
                raise TimeoutError("response lost")
            return await self.respond(request)

        self.query.side_effect = uncertain
        await self.service.check_deadlines()
        self.assertEqual(self.service.latest(1)["state"], "uncertain")
        token = self.service.latest(1)["submission_token"]
        self.service.close()
        self.service = HomeworkService(
            self.directory.name,
            RECIPIENT,
            self.query,
            self.generate,
            self.text,
            self.file,
            render_pdf=self.pdf,
            auto_submit=True,
        )
        self.query.side_effect = self.respond
        await self.service.check_deadlines()
        self.assertEqual(len(self.submissions()), 1)
        self.now += timedelta(seconds=31)
        self.item.update(
            submitted=True, submission_token=token, submission_id="receipt"
        )
        await self.service.check_deadlines()
        self.assertEqual(self.service.latest(1)["state"], "submitted")
        self.assertEqual(len(self.submissions()), 1)

    async def test_authorized_auto_submit_does_not_require_qq_delivery(self):
        self.file.side_effect = RuntimeError("QQ unavailable")
        await self.service.create_draft(1)
        self.assertFalse(self.service.latest(1)["delivered"])
        await self.service.check_deadlines()
        self.assertEqual(self.service.latest(1)["state"], "submitted")
        self.file.assert_awaited_once()
        self.assertTrue(
            any("提交已成功" in call.args[0] for call in self.text.await_args_list)
        )

    async def test_uncertain_receipt_is_reconciled_after_disappearing_from_pending_list_and_deadline(
        self,
    ):
        await self.service.create_draft(1)
        token = "a" * 32 + "1"
        with self.service.db:
            self.service.db.execute(
                "UPDATE drafts SET state='uncertain',submission_token=? WHERE assignment=1",
                (token,),
            )
        self.service.sync([])
        self.now += timedelta(minutes=5)
        self.item.update(
            submitted=True, submission_token=token, submission_id="receipt"
        )
        await self.service.check_deadlines()
        self.assertEqual(self.service.latest(1)["state"], "submitted")
        self.assertFalse(self.submissions())
        self.query.assert_awaited_once_with(
            {"operation": "detail", "assignment_id": self.item["id"]}
        )

    async def test_generation_reaching_deadline_never_uploads_late(self):
        async def slow_model(*args):
            self.now += timedelta(minutes=4)
            return "答案", "test-model"

        self.generate.side_effect = slow_model
        await self.service.check_deadlines()
        self.assertFalse(self.submissions())
        self.assertEqual(self.service.latest(1)["state"], "draft")

    async def test_other_assignment_generation_does_not_hold_deadline_lock(self):
        urgent = self.item.copy()
        future = assignment(2, deadline="2026-09-29 14:00:00")
        self.service.sync([urgent, future])
        await self.service.create_draft(1)
        started, release = asyncio.Event(), asyncio.Event()

        async def slow_model(*args):
            started.set()
            await release.wait()
            return "long answer", "test-model"

        self.generate.side_effect = slow_model
        task = asyncio.create_task(self.service.command("改稿 H2 expand answer"))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.wait_for(self.service.check_deadlines(), timeout=1)
            self.assertEqual(len(self.submissions()), 1)
        finally:
            release.set()
            await task

    async def test_manual_confirmation_and_deadline_check_share_one_submission(self):
        await self.service.create_draft(1)
        await self.service.deliver_draft(self.service.latest(1))
        started, release = asyncio.Event(), asyncio.Event()

        async def blocking_submit(request):
            if request["operation"] == "submit":
                started.set()
                await release.wait()
            return await self.respond(request)

        self.query.side_effect = blocking_submit
        manual = asyncio.create_task(self.service.command("确认 H1 v1"))
        automatic = None
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            automatic = asyncio.create_task(self.service.check_deadlines())
            await asyncio.sleep(0)
            release.set()
            await asyncio.wait_for(asyncio.gather(manual, automatic), timeout=1)
            self.assertEqual(len(self.submissions()), 1)
        finally:
            release.set()
            await manual
            if automatic is not None:
                await automatic


@unittest.skipUnless(
    importlib.util.find_spec("reportlab")
    and importlib.util.find_spec("markdown_it")
    and importlib.util.find_spec("pypdf")
    and Path("/usr/share/fonts/truetype/arphic/uming.ttc").is_file(),
    "PDF worker dependencies and Chinese font required",
)
class HomeworkPdfTests(unittest.TestCase):
    def test_pdf_embeds_chinese_and_keeps_full_multipage_text(self):
        from astrbot_plugin_dududa_notify.homework_pdf import render_pdf
        from pypdf import PdfReader

        content = (
            "# 课堂练习9.24\n\n高级人工智能\n\n机器学习可以看作软约束优化问题。\n\n"
            + "\n\n".join(
                f"{i}. 连续参数采用梯度下降，避免离散回溯的组合爆炸。"
                for i in range(1, 65)
            )
        )
        result = render_pdf(content)
        reader = PdfReader(io.BytesIO(result))
        self.assertGreater(len(reader.pages), 1)
        text = "".join(page.extract_text() for page in reader.pages)
        self.assertIn("课堂练习9.24", text)
        self.assertIn("64.", text)
        fonts = reader.pages[0]["/Resources"]["/Font"]
        self.assertTrue(
            any(
                "/FontFile2" in font.get_object().get("/FontDescriptor", {})
                for font in fonts.values()
            )
        )

    def test_unrequested_transcript_is_not_part_of_submission(self):
        item = assignment(description="解释约束满足问题。")
        records = [
            {"answer": "最终答案。", "question": "private prompt", "comment": ""}
        ]
        content = render_markdown(item, records, 1)
        self.assertIn("最终答案", content)
        self.assertNotIn("private prompt", content)


class HomeworkPrivateCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_quiz_budget_does_not_accept_truncated_model_output(self):
        response = SimpleNamespace(
            completion_text="未完成的答案",
            raw_completion=SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="length")], model="test-model"
            ),
        )
        context = SimpleNamespace(llm_generate=AsyncMock(return_value=response))
        plugin = load_plugin()(context, {"homework_provider_id": "test-provider"})
        with self.assertRaisesRegex(ValueError, "被截断"):
            await plugin._homework_generate("system", "作答方式：小测简答。")
        self.assertEqual(context.llm_generate.await_args.kwargs["max_tokens"], 1200)
        response.raw_completion.choices[0].finish_reason = "stop"
        result = await plugin._homework_generate("system", "作答方式：小测简答。")
        self.assertEqual(result, (response.completion_text, "test-model"))

    async def test_only_owner_on_exact_private_platform_can_confirm(self):
        plugin = load_plugin()(SimpleNamespace(), {})
        plugin.platform_id = "qq"
        plugin.homework = SimpleNamespace(
            owner=RECIPIENT, command=AsyncMock(return_value="")
        )
        event = SimpleNamespace(
            is_private_chat=lambda: True,
            get_sender_id=lambda: RECIPIENT,
            get_self_id=lambda: "bot",
            get_platform_id=lambda: "qq",
            message_str="作业 确认 H1 v1",
            stop_event=Mock(),
        )
        for changes in (
            {"is_private_chat": lambda: False},
            {"get_sender_id": lambda: "other-person"},
            {"get_platform_id": lambda: "other-platform"},
            {"get_self_id": lambda: RECIPIENT},
            {"message_str": "quoted: 作业 确认 H1 v1"},
        ):
            await plugin.homework_message(SimpleNamespace(**{**vars(event), **changes}))
        plugin.homework.command.assert_not_awaited()
        event.stop_event.assert_not_called()
        await plugin.homework_message(event)
        plugin.homework.command.assert_awaited_once_with("确认 H1 v1")
        event.stop_event.assert_called_once()

    async def test_private_file_transport_enforces_recipient(self):
        action = AsyncMock(return_value={})
        platform = SimpleNamespace(
            meta=lambda: SimpleNamespace(id="qq", name="aiocqhttp"),
            get_client=lambda: SimpleNamespace(call_action=action),
        )
        plugin = load_plugin()(
            SimpleNamespace(
                platform_manager=SimpleNamespace(get_insts=lambda: [platform])
            ),
            {},
        )
        plugin.platform_id = "qq"
        plugin.recipients = (RECIPIENT,)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "draft.zip"
        path.write_bytes(b"reviewed-archive")
        await plugin._send_private_file(RECIPIENT, path)
        action.assert_awaited_once_with(
            "upload_private_file",
            user_id=int(RECIPIENT),
            file="base64://" + base64.b64encode(b"reviewed-archive").decode("ascii"),
            name=path.name,
        )
        with self.assertRaisesRegex(ValueError, "not_authorized"):
            await plugin._send_private_file("other-person", path)
        action.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
