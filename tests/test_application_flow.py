import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as application_module
import database
from app import app


class ApplicationFlowTests(unittest.TestCase):
    def setUp(self):
        self.original_store_path = application_module.CHALLENGE_STORE_PATH
        self.temporary_directory = tempfile.TemporaryDirectory()
        application_module.CHALLENGE_STORE_PATH = Path(self.temporary_directory.name) / "challenge_store.json"
        application_module.CHALLENGE_STORE_PATH.write_text(json.dumps({"drafts": {}, "published": {}}), encoding="utf-8")
        self.addCleanup(self.temporary_directory.cleanup)
        self.addCleanup(setattr, application_module, "CHALLENGE_STORE_PATH", self.original_store_path)

        self.records = {}
        self.profile = {"business_id": "startup-001", "business_name": "Example Startup", "business_type": "Startup"}
        replacements = {
            "save_application": self._save_application,
            "get_startup_application": self._get_startup_application,
            "list_startup_applications": self._list_startup_applications,
            "get_application": self._get_application,
            "list_challenge_applications": self._list_challenge_applications,
            "get_government_application": self._get_government_application,
            "count_challenge_applications": self._count_challenge_applications,
            "get_startup_profile": lambda _business_id: self.profile,
            "_startup_is_eligible": lambda _challenge, _profile: True,
            "save_challenge_contract": Mock(),
        }
        for target, replacement in replacements.items():
            patcher = patch.object(application_module, target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _save_application(self, challenge_id, business_id, application_data, status):
        key = (challenge_id, business_id)
        current = self.records.get(key)
        if current and current["status"] != "draft" and not (
            current["status"] == "clarification_requested" and status == "submitted"
        ):
            raise application_module.DuplicateApplicationError
        now = "2026-09-26T12:00:00"
        record = {
            "application_id": current["application_id"] if current else f"APP-{len(self.records) + 1}",
            "challenge_id": challenge_id,
            "business_id": business_id,
            "status": status,
            "application_data": dict(application_data),
            "submitted_at": (current or {}).get("submitted_at") or (now if status == "submitted" else None),
            "updated_at": now,
        }
        self.records[key] = record
        return dict(record)

    def _get_startup_application(self, challenge_id, business_id):
        record = self.records.get((challenge_id, business_id))
        return dict(record) if record else None

    def _list_startup_applications(self, business_id):
        return [dict(record) for (_, owner), record in self.records.items() if owner == business_id]

    def _get_application(self, application_id, business_id):
        return next(
            (dict(record) for record in self.records.values()
             if record["application_id"] == application_id and record["business_id"] == business_id),
            None,
        )

    def _list_challenge_applications(self, challenge_id):
        return [
            {**record, "startup_name": self.profile["business_name"]}
            for (challenge, _owner), record in self.records.items()
            if challenge == challenge_id and record["status"] != "draft"
        ]

    def _get_government_application(self, application_id):
        return next(
            ({**record, "startup_name": self.profile["business_name"]} for record in self.records.values()
             if record["application_id"] == application_id and record["status"] != "draft"),
            None,
        )

    def _count_challenge_applications(self, challenge_id):
        return sum(
            1 for (challenge, _owner), record in self.records.items()
            if challenge == challenge_id and record["status"] != "draft"
        )

    def _startup_client(self, business_id="startup-001"):
        client = app.test_client()
        with client.session_transaction() as session:
            session["role"] = "startup"
            session["business_id"] = business_id
        return client

    def _ministry_client(self, ministry_id="admin"):
        client = app.test_client()
        with client.session_transaction() as session:
            session["role"] = "ministry"
            session["ministry_id"] = ministry_id
        return client

    def _publishable_challenge(self, challenge_id="GOV-APPLY-001", created_by="admin", status="start bidding"):
        challenge = {
            "id": challenge_id.lower(),
            "challengeId": challenge_id,
            "title": "Application Test Challenge",
            "status": status,
            "createdBy": created_by,
            "ministry": "Test Government",
            "department": "Test Department",
            "state": "Maharashtra",
            "eligibility": {"participantTypes": ["Startups"]},
            "timeline": {"submissionDeadline": "2027-12-31"},
        }
        store = application_module._read_store()
        store["published"][challenge["id"]] = challenge
        application_module._write_store(store)
        return challenge

    def _required_answers(self):
        return {key: f"Answer for {key}" for key in application_module.REQUIRED_APPLICATION_FIELDS}

    def _application_request(self, client, challenge_id="GOV-APPLY-001", action="draft", answers=None, **extra):
        return client.post(
            f"/api/challenges/{challenge_id}/applications",
            json={"action": action, "application_data": answers or {}, **extra},
        )

    def test_startup_can_create_and_update_own_draft(self):
        self._publishable_challenge()
        client = self._startup_client()
        created = self._application_request(client, answers={"problem_addressed": "Initial draft"})
        self.assertEqual(created.status_code, 200)
        application_id = created.get_json()["application"]["application_id"]
        updated = self._application_request(client, answers={"problem_addressed": "Updated draft"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["application"]["application_id"], application_id)
        self.assertEqual(updated.get_json()["application"]["application_data"]["problem_addressed"], "Updated draft")

    def test_startup_can_submit_and_record_persists_across_sessions(self):
        self._publishable_challenge()
        first_session = self._startup_client()
        response = self._application_request(first_session, action="submit", answers=self._required_answers())
        self.assertEqual(response.status_code, 200)
        application = response.get_json()["application"]
        self.assertEqual(application["status"], "submitted")
        self.assertIsNotNone(application["submitted_at"])
        listed = self._startup_client().get("/api/applications").get_json()["applications"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["application_id"], application["application_id"])

    def test_business_identity_comes_from_session_not_request(self):
        self._publishable_challenge()
        client = self._startup_client("session-business")
        response = self._application_request(client, business_id="forged-business", answers={"problem_addressed": "Draft"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(("GOV-APPLY-001", "session-business"), self.records)
        self.assertNotIn(("GOV-APPLY-001", "forged-business"), self.records)

    def test_duplicate_application_is_rejected_and_submitted_record_is_locked(self):
        self._publishable_challenge()
        client = self._startup_client()
        self.assertEqual(self._application_request(client, action="submit", answers=self._required_answers()).status_code, 200)
        rejected = self._application_request(client, action="draft", answers={"problem_addressed": "Overwrite"})
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(self.records[("GOV-APPLY-001", "startup-001")]["status"], "submitted")

    def test_startup_can_view_only_its_own_application(self):
        self._publishable_challenge()
        own_client = self._startup_client()
        submitted = self._application_request(own_client, action="submit", answers=self._required_answers()).get_json()["application"]
        self.assertEqual(own_client.get(f"/api/applications/{submitted['application_id']}").status_code, 200)
        self.assertEqual(self._startup_client("startup-002").get(
            f"/api/applications/{submitted['application_id']}"
        ).status_code, 404)

    def test_government_can_list_count_and_open_submitted_applications(self):
        self._publishable_challenge(created_by="admin")
        startup = self._startup_client()
        application = self._application_request(startup, action="submit", answers=self._required_answers()).get_json()["application"]
        ministry = self._ministry_client("admin")
        listing = ministry.get("/api/challenges/GOV-APPLY-001/applications")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()["count"], 1)
        opened = ministry.get(f"/api/government/applications/{application['application_id']}")
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.get_json()["application"]["status"], "submitted")
        self.assertEqual(self._ministry_client("other-ministry").get(
            f"/api/government/applications/{application['application_id']}"
        ).status_code, 403)

    def test_drafts_are_not_in_government_application_count(self):
        self._publishable_challenge()
        self._application_request(self._startup_client(), answers={"problem_addressed": "Draft"})
        response = self._ministry_client().get("/api/challenges/GOV-APPLY-001/applications")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 0)
        self.assertEqual(response.get_json()["applications"], [])

    def test_missing_required_fields_prevent_submission(self):
        self._publishable_challenge()
        response = self._application_request(self._startup_client(), action="submit", answers={"problem_addressed": "Only one answer"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("challenge_solution", response.get_json()["missing"])

    def test_nonexistent_and_closed_challenges_reject_applications(self):
        client = self._startup_client()
        self.assertEqual(self._application_request(client, "GOV-NOT-FOUND").status_code, 404)
        self._publishable_challenge(status="closed")
        response = self._application_request(client, action="submit", answers=self._required_answers())
        self.assertEqual(response.status_code, 400)

    def test_application_api_rejects_non_startup_sessions(self):
        self._publishable_challenge()
        anonymous = app.test_client()
        self.assertEqual(anonymous.get("/api/applications").status_code, 401)
        self.assertEqual(self._ministry_client().post(
            "/api/challenges/GOV-APPLY-001/applications", json={"action": "draft", "application_data": {}}
        ).status_code, 401)

    def test_startup_page_shows_restored_sample_challenges_and_my_applications(self):
        content = self._startup_client().get("/startup-portal").get_data(as_text=True)
        self.assertIn("My Applications", content)
        self.assertIn("Sample record", content)
        self.assertIn("Low-cost remote screening for diabetic retinopathy", content)

    def test_application_page_shows_sample_context_and_form_without_business_id_input(self):
        response = self._startup_client().get("/contracts/PS-MH-038/apply")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("Low-cost remote screening for diabetic retinopathy", content)
        self.assertIn("Problem statement", content)
        self.assertIn("Evaluation criteria", content)
        self.assertIn("Sample record", content)
        for field in ("problem_addressed", "challenge_solution", "technology_approach", "expected_timeline", "supporting_evidence"):
            self.assertIn(f'name="{field}"', content)
        self.assertNotIn('name="business_id"', content)

    def test_real_published_challenges_remain_alongside_sample_challenges(self):
        response = self._ministry_client().post("/api/challenges", json={"challenge": {
            "challengeId": "GOV-REAL-STEP-2",
            "title": "New government challenge",
            "status": "Published",
            "evaluationCriteria": [{"criterion": "Impact", "weight": 100}],
        }})
        self.assertEqual(response.status_code, 200)
        public = app.test_client().get("/api/public/challenges").get_json()["challenges"]
        by_id = {item["challengeId"]: item for item in public}
        self.assertTrue(by_id["PS-MH-038"]["isSample"])
        self.assertFalse(by_id["GOV-REAL-STEP-2"]["isSample"])

    def test_application_schema_has_unique_pair_and_useful_indexes(self):
        schema = database.APPLICATIONS_SCHEMA_SQL
        for field in ("application_id", "challenge_id", "business_id_encrypted", "status", "application_data", "submitted_at", "updated_at"):
            self.assertIn(field, schema)
        self.assertIn("uq_applications_challenge_business", schema)
        for index in ("idx_applications_challenge", "idx_applications_business", "idx_applications_status"):
            self.assertIn(index, schema)

    def test_application_count_sql_excludes_drafts(self):
        cursor = Mock()
        cursor.fetchone.return_value = (2,)
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            self.assertEqual(database.count_challenge_applications("GOV-APPLY-001"), 2)
        self.assertIn("status <> 'draft'", cursor.execute.call_args_list[-1].args[0])
