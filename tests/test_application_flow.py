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
        self.screening_records = {}
        self.audit_records = {}
        self.evaluations = {}
        self.shortlist_decisions = {}
        self.shortlist_audit_records = {}
        self.profile = {"business_id": "startup-001", "business_name": "Example Startup", "business_type": "Startup"}
        replacements = {
            "save_application": self._save_application,
            "get_startup_application": self._get_startup_application,
            "list_startup_applications": self._list_startup_applications,
            "get_application": self._get_application,
            "list_challenge_applications": self._list_challenge_applications,
            "get_government_application": self._get_government_application,
            "get_application_screening": self._get_application_screening,
            "start_application_screening": self._start_application_screening,
            "save_application_screening": self._save_application_screening,
            "finalize_application_screening": self._finalize_application_screening,
            "start_application_evaluation": self._start_application_evaluation,
            "get_application_evaluation": self._get_application_evaluation,
            "save_application_evaluation": self._save_application_evaluation,
            "complete_application_evaluation": self._complete_application_evaluation,
            "list_challenge_evaluation_comparison": self._list_challenge_evaluation_comparison,
            "record_application_shortlist_decision": self._record_application_shortlist_decision,
            "get_application_shortlist_history": self._get_application_shortlist_history,
            "get_startup_clarification_request": self._get_startup_clarification_request,
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
        if current and current["status"] == "clarification_requested" and status == "submitted":
            self._record_audit(record["application_id"], business_id, "startup", "clarification_response", {})
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

    def _record_audit(self, application_id, reviewer_id, reviewer_role, event_type, details):
        self.audit_records.setdefault(application_id, []).append({
            "event_type": event_type,
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "details": dict(details),
            "created_at": "2026-09-26T12:00:00",
        })

    def _get_application_screening(self, application_id, business_id=None):
        if business_id is not None:
            owner_record = next((record for record in self.records.values()
                                 if record["application_id"] == application_id and record["business_id"] == business_id), None)
            if owner_record is None:
                return {"requirements": [], "audit": []}
        requirements = list(self.screening_records.get(application_id, {}).values())
        return {"requirements": requirements, "audit": list(self.audit_records.get(application_id, []))}

    def _start_application_screening(self, application_id, reviewer_id, reviewer_role):
        record = next((item for item in self.records.values() if item["application_id"] == application_id), None)
        if not record or record["status"] == "draft":
            return False
        self._record_audit(application_id, reviewer_id, reviewer_role, "screening_started", {})
        return True

    def _save_application_screening(self, application_id, reviewer_id, reviewer_role, requirements):
        record = next((item for item in self.records.values() if item["application_id"] == application_id), None)
        if not record or record["status"] not in {"submitted", "clarification_requested"}:
            raise ValueError("This application is not available for eligibility screening.")
        saved = self.screening_records.setdefault(application_id, {})
        for item in requirements:
            saved[item["requirement"]] = {
                **item,
                "reviewer_id": reviewer_id,
                "reviewer_role": reviewer_role,
                "created_at": "2026-09-26T12:00:00",
            }

    def _finalize_application_screening(self, application_id, reviewer_id, reviewer_role, decision, details):
        record = next((item for item in self.records.values() if item["application_id"] == application_id), None)
        if not record or record["status"] != "submitted":
            return False
        record["status"] = decision
        event_type = {
            "eligible": "eligibility_approved",
            "ineligible": "eligibility_rejected",
            "clarification_requested": "clarification_requested",
        }[decision]
        self._record_audit(application_id, reviewer_id, reviewer_role, event_type, details)
        return True

    def _start_application_evaluation(self, application_id, reviewer_id, reviewer_role, criteria):
        record = next((item for item in self.records.values() if item["application_id"] == application_id), None)
        if not record or record["status"] != "eligible":
            return False
        self.evaluations[application_id] = {
            "evaluation_id": f"EVAL-{application_id}",
            "application_id": application_id,
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "status": "in_progress",
            "total_score": 0.0,
            "maximum_total_score": sum(item["weight"] for item in criteria),
            "started_at": "2026-09-26T12:00:00",
            "completed_at": None,
            "criteria": [{**item, "score": None, "comment": "", "reviewer_id": reviewer_id, "reviewer_role": reviewer_role} for item in criteria],
            "history": [],
        }
        record["status"] = "under_evaluation"
        self._evaluation_event(application_id, reviewer_id, reviewer_role, "evaluation_started", {})
        self._record_audit(application_id, reviewer_id, reviewer_role, "evaluation_started", {})
        return True

    def _evaluation_event(self, application_id, reviewer_id, reviewer_role, event_type, details):
        self.evaluations[application_id]["history"].append({
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
            "event_type": event_type,
            "details": dict(details),
            "created_at": "2026-09-26T12:00:00",
        })

    def _get_application_evaluation(self, application_id):
        evaluation = self.evaluations.get(application_id)
        return json.loads(json.dumps(evaluation)) if evaluation else None

    def _save_application_evaluation(self, application_id, reviewer_id, reviewer_role, scores):
        evaluation = self.evaluations.get(application_id)
        if not evaluation or evaluation["status"] != "in_progress":
            raise ValueError("Only applications under evaluation can be edited.")
        for score in scores:
            criterion = next((item for item in evaluation["criteria"] if item["criterion"] == score["criterion"]), None)
            if criterion is None:
                raise ValueError("An evaluation criterion is invalid.")
            criterion.update({"score": score["score"], "comment": score["comment"], "reviewer_id": reviewer_id, "reviewer_role": reviewer_role})
        total = sum((item["score"] / item["maximum_score"]) * item["weight"] for item in evaluation["criteria"] if item["score"] is not None)
        evaluation.update({"total_score": round(total, 2), "maximum_total_score": sum(item["weight"] for item in evaluation["criteria"]), "reviewer_id": reviewer_id, "reviewer_role": reviewer_role})
        self._evaluation_event(application_id, reviewer_id, reviewer_role, "evaluation_saved", {"total_score": evaluation["total_score"]})
        return {"total_score": evaluation["total_score"], "maximum_total_score": evaluation["maximum_total_score"]}

    def _complete_application_evaluation(self, application_id, reviewer_id, reviewer_role):
        record = next((item for item in self.records.values() if item["application_id"] == application_id), None)
        evaluation = self.evaluations.get(application_id)
        if not record or record["status"] != "under_evaluation" or not evaluation or evaluation["status"] != "in_progress":
            raise ValueError("Only applications under evaluation can be completed.")
        if any(item["required"] and item["score"] is None for item in evaluation["criteria"]):
            raise ValueError("Complete every required criterion before completing evaluation.")
        totals = self._save_application_evaluation(application_id, reviewer_id, reviewer_role, [])
        record["status"] = "evaluation_complete"
        evaluation["status"] = "evaluation_complete"
        evaluation["completed_at"] = "2026-09-26T12:00:00"
        self._evaluation_event(application_id, reviewer_id, reviewer_role, "evaluation_completed", totals)
        self._record_audit(application_id, reviewer_id, reviewer_role, "evaluation_completed", totals)
        return totals

    def _list_challenge_evaluation_comparison(self, challenge_id):
        results = []
        for (challenge, _owner), record in self.records.items():
            evaluation = self.evaluations.get(record["application_id"])
            if challenge != challenge_id or record["status"] not in {"evaluation_complete", "shortlisted", "not_selected"} or not evaluation or evaluation["status"] != "evaluation_complete":
                continue
            decision = self.shortlist_decisions.get(record["application_id"])
            results.append({
                **record,
                "startup_name": self.profile["business_name"],
                "total_score": evaluation["total_score"],
                "maximum_total_score": evaluation["maximum_total_score"],
                "evaluation_completed_at": evaluation["completed_at"],
                "selection_status": decision["decision"] if decision else "Pending Decision",
                "decision_maker": decision["decision_maker"] if decision else None,
                "decision_role": decision["decision_role"] if decision else None,
                "decision_comments": decision["comments"] if decision else "",
                "decision_at": decision["created_at"] if decision else None,
            })
        return results

    def _record_application_shortlist_decision(self, application_id, decision, decision_maker, decision_role, comments):
        record = next((item for item in self.records.values() if item["application_id"] == application_id), None)
        evaluation = self.evaluations.get(application_id)
        if not record or record["status"] != "evaluation_complete" or not evaluation or evaluation["status"] != "evaluation_complete":
            return False
        if application_id in self.shortlist_decisions:
            return False
        decision_record = {
            "decision": decision,
            "decision_maker": decision_maker,
            "decision_role": decision_role,
            "comments": comments,
            "created_at": "2026-09-26T12:00:00",
        }
        self.shortlist_decisions[application_id] = decision_record
        record["status"] = decision
        self.shortlist_audit_records.setdefault(application_id, []).append({
            "decision_maker": decision_maker,
            "decision_role": decision_role,
            "event_type": "application_shortlisted" if decision == "shortlisted" else "application_not_selected",
            "details": {"decision": decision, "comments": comments},
            "created_at": decision_record["created_at"],
        })
        return True

    def _get_application_shortlist_history(self, application_id):
        decision = self.shortlist_decisions.get(application_id)
        return {
            "decision": dict(decision) if decision else None,
            "history": list(self.shortlist_audit_records.get(application_id, [])),
        }

    def _get_startup_clarification_request(self, application_id, business_id):
        owner_record = next((record for record in self.records.values()
                             if record["application_id"] == application_id and record["business_id"] == business_id
                             and record["status"] == "clarification_requested"), None)
        if owner_record is None:
            return []
        return [item for item in self.screening_records.get(application_id, {}).values()
                if item["decision"] == "needs_clarification"]

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
            "evaluationCriteria": [
                {"criterion": "Technical Feasibility", "description": "Technical viability", "weight": 60},
                {"criterion": "Expected Impact", "description": "Public impact", "weight": 40, "required": False},
            ],
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

    def _submitted_application(self, challenge_id="GOV-APPLY-001"):
        challenge = self._publishable_challenge(challenge_id=challenge_id)
        response = self._application_request(
            self._startup_client(), challenge_id=challenge_id, action="submit", answers=self._required_answers()
        )
        self.assertEqual(response.status_code, 200)
        return challenge, response.get_json()["application"]

    def _screening_requirements(self, challenge, decision="pass", override=None):
        results = []
        for index, requirement in enumerate(application_module._eligibility_requirements(challenge)):
            results.append({
                "requirement": requirement,
                "decision": (override or {}).get(index, decision),
                "comment": f"Reviewer note for {requirement}",
            })
        return results

    def _screen_application(self, application_id, challenge, action, requirements=None, client=None):
        return (client or self._ministry_client()).post(
            f"/api/government/applications/{application_id}/screening",
            json={"action": action, "requirements": requirements or self._screening_requirements(challenge)},
        )

    def _approved_evaluation(self):
        challenge, application = self._submitted_application()
        self.assertEqual(self._screen_application(application["application_id"], challenge, "eligible").status_code, 200)
        response = self._ministry_client().post(
            f"/api/government/applications/{application['application_id']}/evaluation/start"
        )
        self.assertEqual(response.status_code, 200)
        return challenge, application

    def _completed_evaluation(self):
        challenge, application = self._approved_evaluation()
        ministry = self._ministry_client()
        saved = ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation",
            json={"criteria": [{"criterion": "Technical Feasibility", "score": 75, "comment": "Strong implementation."}]},
        )
        self.assertEqual(saved.status_code, 200)
        completed = ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation/complete"
        )
        self.assertEqual(completed.status_code, 200)
        return challenge, application

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

    def test_ministry_can_view_real_challenge_applications_with_filters(self):
        self._submitted_application()
        ministry = self._ministry_client()
        queue = ministry.get("/government-dashboard/GOV-APPLY-001/applications")
        self.assertEqual(queue.status_code, 200)
        content = queue.get_data(as_text=True)
        self.assertIn("APP-1", content)
        self.assertIn("Example Startup", content)
        self.assertIn("Eligibility: Pending", content)
        self.assertIn("Evaluation: Not Started", content)
        self.assertEqual(len(self.records), 1)
        self.assertEqual(len(self._list_challenge_applications("GOV-APPLY-001")), 1)
        self.assertEqual(ministry.get("/government-dashboard/GOV-APPLY-001/applications?status=eligible").status_code, 200)
        self.assertNotIn("APP-1", ministry.get("/government-dashboard/GOV-APPLY-001/applications?status=eligible").get_data(as_text=True))
        self.assertEqual(self._startup_client().get("/government-dashboard/GOV-APPLY-001/applications").status_code, 302)

    def test_comparison_screen_shows_completed_evaluations_and_selection_actions(self):
        challenge, completed = self._completed_evaluation()
        self._publishable_challenge()
        pending_response = self._application_request(
            self._startup_client("startup-002"), action="submit", answers=self._required_answers()
        )
        self.assertEqual(pending_response.status_code, 200)
        pending = pending_response.get_json()["application"]
        pending_challenge = self._read_store_challenge(challenge["challengeId"])
        self.assertEqual(self._screen_application(pending["application_id"], pending_challenge, "eligible").status_code, 200)
        self.assertEqual(self._ministry_client().post(
            f"/api/government/applications/{pending['application_id']}/evaluation/start"
        ).status_code, 200)

        response = self._ministry_client().get(f"/government-dashboard/{challenge['challengeId']}/comparison")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("Evaluation comparison", content)
        self.assertIn("Example Startup", content)
        self.assertIn(completed["application_id"], content)
        self.assertNotIn(pending["application_id"], content)
        for column in ("Eligibility", "Evaluation status", "Total evaluation score", "Key solution information", "Selection status"):
            self.assertIn(column, content)
        self.assertIn("Shortlist", content)
        self.assertIn("Not Selected", content)
        self.assertIn("score is informational only", content)

    def _read_store_challenge(self, challenge_id):
        return next(item for item in application_module._serialize_challenges() if item.get("challengeId") == challenge_id)

    def test_ministry_can_shortlist_and_decision_persists_with_audit(self):
        challenge, application = self._completed_evaluation()
        reviewer = self._ministry_client()
        response = reviewer.post(
            f"/api/government/applications/{application['application_id']}/shortlist",
            json={"decision": "shortlisted", "comments": "Strong fit for the next decision stage."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "shortlisted")
        comparison = reviewer.get(f"/government-dashboard/{challenge['challengeId']}/comparison").get_data(as_text=True)
        self.assertIn("Shortlisted", comparison)
        self.assertIn("Strong fit for the next decision stage.", comparison)
        detail = reviewer.get(f"/government-applications/{application['application_id']}").get_data(as_text=True)
        self.assertIn("Shortlist decision", detail)
        history = reviewer.get(f"/api/government/applications/{application['application_id']}").get_json()["shortlist"]
        self.assertEqual(history["decision"]["decision_maker"], "admin")
        self.assertEqual(history["decision"]["decision_role"], "ministry")
        self.assertEqual(history["decision"]["comments"], "Strong fit for the next decision stage.")
        self.assertEqual(history["history"][0]["event_type"], "application_shortlisted")

    def test_ministry_can_mark_not_selected_and_keep_audit_history(self):
        challenge, application = self._completed_evaluation()
        reviewer = self._ministry_client()
        response = reviewer.post(
            f"/api/government/applications/{application['application_id']}/shortlist",
            json={"decision": "not_selected", "comments": "Does not meet the current portfolio priorities."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "not_selected")
        history = reviewer.get(f"/api/government/applications/{application['application_id']}").get_json()["shortlist"]
        self.assertEqual(history["decision"]["decision"], "not_selected")
        self.assertEqual(history["history"][0]["event_type"], "application_not_selected")
        comparison = reviewer.get(f"/government-dashboard/{challenge['challengeId']}/comparison").get_data(as_text=True)
        self.assertIn("Not Selected", comparison)
        self.assertIn(application["application_id"], comparison)

    def test_startup_and_nonowner_ministry_cannot_shortlist(self):
        challenge, application = self._completed_evaluation()
        url = f"/api/government/applications/{application['application_id']}/shortlist"
        decision = {"decision": "shortlisted", "comments": "Explicit ministry decision."}
        self.assertEqual(self._startup_client().post(url, json=decision).status_code, 401)
        other_ministry = self._ministry_client("other-ministry")
        self.assertEqual(other_ministry.post(url, json=decision).status_code, 403)
        self.assertEqual(other_ministry.get(f"/government-dashboard/{challenge['challengeId']}/comparison").status_code, 403)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "evaluation_complete")

    def test_shortlist_decision_requires_completed_evaluation_and_reason(self):
        challenge, application = self._submitted_application()
        ministry = self._ministry_client()
        url = f"/api/government/applications/{application['application_id']}/shortlist"
        self.assertEqual(ministry.post(url, json={"decision": "shortlisted", "comments": "Reason"}).status_code, 409)

        self.assertEqual(self._screen_application(application["application_id"], challenge, "eligible", client=ministry).status_code, 200)
        self.assertEqual(ministry.post(f"/api/government/applications/{application['application_id']}/evaluation/start").status_code, 200)
        self.assertEqual(ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation",
            json={"criteria": [{"criterion": "Technical Feasibility", "score": 70, "comment": "Reviewed."}]},
        ).status_code, 200)
        self.assertEqual(ministry.post(f"/api/government/applications/{application['application_id']}/evaluation/complete").status_code, 200)
        self.assertEqual(ministry.post(url, json={"decision": "shortlisted", "comments": ""}).status_code, 400)
        self.assertEqual(ministry.post(url, json={"decision": "shortlisted", "comments": "Reason"}).status_code, 200)
        self.assertEqual(ministry.post(url, json={"decision": "not_selected", "comments": "Changed later"}).status_code, 409)

    def test_ministry_application_detail_shows_actual_answers_and_challenge_eligibility(self):
        challenge, application = self._submitted_application()
        response = self._ministry_client().get(f"/government-applications/{application['application_id']}")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("Application Test Challenge", content)
        self.assertIn("Problem understanding", content)
        self.assertIn("Answer for problem_addressed", content)
        self.assertIn("Technology / approach", content)
        self.assertIn("Original challenge context", content)
        self.assertIn("Eligible participant types: Startups", content)
        self.assertIn("data-requirement-row", content)

    def test_other_ministry_cannot_open_application_detail_or_screening(self):
        challenge, application = self._submitted_application()
        other_ministry = self._ministry_client("different-ministry")
        self.assertEqual(other_ministry.get(
            f"/government-applications/{application['application_id']}"
        ).status_code, 403)
        self.assertEqual(other_ministry.post(
            f"/api/government/applications/{application['application_id']}/screening/start"
        ).status_code, 403)

    def test_startup_cannot_access_ministry_screening_apis(self):
        _challenge, application = self._submitted_application()
        application_id = application["application_id"]
        startup = self._startup_client()
        for suffix in ("screening/start", "screening", "evaluation/start"):
            response = startup.post(f"/api/government/applications/{application_id}/{suffix}", json={})
            self.assertEqual(response.status_code, 401)

    def test_ministry_can_mark_eligible_and_enter_evaluation(self):
        challenge, application = self._submitted_application()
        reviewer = self._ministry_client()
        started = reviewer.post(f"/api/government/applications/{application['application_id']}/screening/start")
        self.assertEqual(started.status_code, 200)
        decision = self._screen_application(application["application_id"], challenge, "eligible", client=reviewer)
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "eligible")

        view = reviewer.get(f"/api/government/applications/{application['application_id']}").get_json()
        self.assertEqual(view["application"]["eligibility_status"], "Eligible")
        events = [item["event_type"] for item in view["screening"]["audit"]]
        self.assertIn("screening_started", events)
        self.assertIn("eligibility_approved", events)
        approval_event = next(item for item in view["screening"]["audit"] if item["event_type"] == "eligibility_approved")
        self.assertEqual(approval_event["reviewer_id"], "admin")
        self.assertEqual(approval_event["reviewer_role"], "ministry")
        requirements = view["screening"]["requirements"]
        self.assertEqual(len(requirements), len(application_module._eligibility_requirements(challenge)))
        self.assertEqual(requirements[0]["reviewer_id"], "admin")
        self.assertEqual(requirements[0]["reviewer_role"], "ministry")
        detail_page = reviewer.get(f"/government-applications/{application['application_id']}").get_data(as_text=True)
        self.assertIn("Recorded eligibility decisions", detail_page)
        self.assertIn("Decision: Pass", detail_page)

        entered = reviewer.post(f"/api/government/applications/{application['application_id']}/evaluation/start")
        self.assertEqual(entered.status_code, 200)
        evaluation_response = reviewer.get(f"/api/government/applications/{application['application_id']}").get_json()
        status_after_entry = evaluation_response["application"]
        self.assertEqual(status_after_entry["status"], "under_evaluation")
        self.assertEqual(status_after_entry["eligibility_status"], "Eligible")
        self.assertEqual([item["criterion"] for item in evaluation_response["evaluation"]["criteria"]], ["Technical Feasibility", "Expected Impact"])
        self.assertFalse(evaluation_response["evaluation"]["criteria"][1]["required"])
        detail = reviewer.get(f"/government-applications/{application['application_id']}").get_data(as_text=True)
        self.assertIn("Evaluation Scorecard", detail)
        self.assertIn("Technical Feasibility", detail)
        self.assertIn("Save Evaluation", detail)
        self.assertIn("Complete Evaluation", detail)

    def test_ministry_can_mark_ineligible_and_evaluation_remains_locked(self):
        challenge, application = self._submitted_application()
        requirements = self._screening_requirements(challenge, override={0: "fail"})
        decision = self._screen_application(application["application_id"], challenge, "ineligible", requirements)
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "ineligible")
        evaluation = self._ministry_client().post(
            f"/api/government/applications/{application['application_id']}/evaluation/start"
        )
        self.assertEqual(evaluation.status_code, 409)
        events = self.audit_records[application["application_id"]]
        self.assertIn("eligibility_rejected", [item["event_type"] for item in events])

    def test_evaluation_score_cannot_exceed_criterion_maximum(self):
        _challenge, application = self._approved_evaluation()
        response = self._ministry_client().post(
            f"/api/government/applications/{application['application_id']}/evaluation",
            json={"criteria": [{"criterion": "Technical Feasibility", "score": 101, "comment": "Over limit"}]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("between 0 and 100", response.get_json()["message"])

    def test_evaluation_total_is_calculated_and_persists(self):
        _challenge, application = self._approved_evaluation()
        ministry = self._ministry_client()
        response = ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation",
            json={
                "criteria": [
                    {"criterion": "Technical Feasibility", "score": 50, "comment": "Sound architecture."},
                    {"criterion": "Expected Impact", "score": 80, "comment": "Strong reach."},
                ],
                "total_score": 999,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total_score"], 62.0)
        saved = ministry.get(f"/api/government/applications/{application['application_id']}").get_json()["evaluation"]
        self.assertEqual(saved["total_score"], 62.0)
        self.assertEqual(saved["criteria"][0]["comment"], "Sound architecture.")
        self.assertEqual(saved["status"], "in_progress")

    def test_required_evaluation_criteria_must_be_scored_before_completion(self):
        _challenge, application = self._approved_evaluation()
        ministry = self._ministry_client()
        completed_early = ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation/complete"
        )
        self.assertEqual(completed_early.status_code, 409)
        self.assertIn("required criterion", completed_early.get_json()["message"])

        saved = ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation",
            json={"criteria": [{"criterion": "Technical Feasibility", "score": 75, "comment": "Adequate."}]},
        )
        self.assertEqual(saved.status_code, 200)
        completed = ministry.post(
            f"/api/government/applications/{application['application_id']}/evaluation/complete"
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(self.records[(application["challenge_id"], "startup-001")]["status"], "evaluation_complete")
        result = ministry.get(f"/api/government/applications/{application['application_id']}").get_json()
        self.assertEqual(result["evaluation"]["status"], "evaluation_complete")
        self.assertIsNotNone(result["evaluation"]["completed_at"])
        self.assertIn("evaluation_completed", [item["event_type"] for item in result["evaluation"]["history"]])
        self.assertEqual(result["application"]["application_data"], application["application_data"])
        eligible_queue = ministry.get("/government-dashboard/GOV-APPLY-001/applications?status=eligible").get_data(as_text=True)
        self.assertIn(application["application_id"], eligible_queue)

    def test_startup_cannot_access_evaluation_apis(self):
        _challenge, application = self._submitted_application()
        startup = self._startup_client()
        for suffix in ("evaluation/start", "evaluation", "evaluation/complete"):
            response = startup.post(f"/api/government/applications/{application['application_id']}/{suffix}", json={})
            self.assertEqual(response.status_code, 401)

    def test_ministry_can_request_clarification_and_startup_can_respond(self):
        challenge, application = self._submitted_application()
        requirements = self._screening_requirements(challenge, override={0: "needs_clarification"})
        requirements[0]["comment"] = "Please provide evidence for this requirement."
        decision = self._screen_application(application["application_id"], challenge, "clarification_requested", requirements)
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "clarification_requested")

        startup = self._startup_client()
        application_page = startup.get("/contracts/GOV-APPLY-001/apply")
        self.assertEqual(application_page.status_code, 200)
        self.assertIn("Please provide evidence for this requirement.", application_page.get_data(as_text=True))
        response = self._application_request(
            startup,
            action="respond",
            answers={"clarification_response": "Evidence attached to our registration."},
        )
        self.assertEqual(response.status_code, 200)
        updated = response.get_json()["application"]
        self.assertEqual(updated["status"], "submitted")
        self.assertEqual(updated["application_data"]["clarification_response"], "Evidence attached to our registration.")
        self.assertIn("clarification_response", [item["event_type"] for item in self.audit_records[application["application_id"]]])
        returned_to_review = self._ministry_client().get("/api/challenges/GOV-APPLY-001/applications").get_json()["applications"]
        self.assertEqual(returned_to_review[0]["status"], "submitted")

    def test_clarification_request_requires_reviewer_comment(self):
        challenge, application = self._submitted_application()
        requirements = self._screening_requirements(challenge, override={0: "needs_clarification"})
        requirements[0]["comment"] = ""
        response = self._screen_application(application["application_id"], challenge, "clarification_requested", requirements)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.records[(challenge["challengeId"], "startup-001")]["status"], "submitted")

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

    def test_both_roles_can_sign_out_without_a_switch_account_option(self):
        for role in ("startup", "ministry"):
            client = app.test_client()
            with client.session_transaction() as session:
                session["role"] = role
            page = client.get("/login")
            content = page.get_data(as_text=True)
            self.assertEqual(page.status_code, 200)
            self.assertIn("Startup sign in", content)
            self.assertIn("Ministry sign in", content)
            self.assertNotIn("Switch account", content)
            self.assertIn("Sign out", content)
            self.assertEqual(client.post("/api/logout").status_code, 200)
            self.assertIn("Sign in", client.get("/login").get_data(as_text=True))

    def test_ministry_landing_is_a_workspace_with_create_action(self):
        response = self._ministry_client().get("/ministry-portal")
        self.assertEqual(response.status_code, 200)
        content = response.get_data(as_text=True)
        self.assertIn("Create New Challenge", content)
        self.assertIn('href="/create-challenge"', content)
        self.assertIn('href="/government-dashboard"', content)
        self.assertIn('href="/periodic-checks"', content)

    def test_periodic_checks_are_separate_from_challenge_creation_and_management(self):
        self._publishable_challenge()
        ministry = self._ministry_client()
        self.assertEqual(app.test_client().get("/periodic-checks").status_code, 302)

        checks = ministry.get("/periodic-checks")
        self.assertEqual(checks.status_code, 200)
        self.assertIn("data-schedule-form", checks.get_data(as_text=True))
        self.assertIn("periodic-reports", checks.get_data(as_text=True))

        portfolio = ministry.get("/government-dashboard").get_data(as_text=True)
        self.assertIn("/periodic-checks#check-GOV-APPLY-001", portfolio)
        self.assertNotIn("data-schedule-form", portfolio)
        self.assertNotIn("periodic-reports", portfolio)

        create_page = ministry.get("/create-challenge").get_data(as_text=True)
        self.assertNotIn("data-schedule-form", create_page)

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
        screening_schema = database.APPLICATION_SCREENINGS_SCHEMA_SQL
        for field in ("application_id", "reviewer_id", "reviewer_role", "requirement", "decision", "comment", "created_at"):
            self.assertIn(field, screening_schema)
        audit_schema = database.APPLICATION_SCREENING_AUDIT_SCHEMA_SQL
        for field in ("application_id", "reviewer_id", "reviewer_role", "event_type", "details", "created_at"):
            self.assertIn(field, audit_schema)
        evaluation_schema = database.APPLICATION_EVALUATIONS_SCHEMA_SQL
        for field in ("application_id", "reviewer_id", "reviewer_role", "total_score", "status", "started_at", "completed_at"):
            self.assertIn(field, evaluation_schema)
        score_schema = database.APPLICATION_EVALUATION_SCORES_SCHEMA_SQL
        for field in ("criterion", "score", "maximum_score", "weight", "is_required", "comment"):
            self.assertIn(field, score_schema)
        self.assertIn("application_evaluation_audit", database.APPLICATION_EVALUATION_AUDIT_SCHEMA_SQL)
        for field in ("application_id", "decision", "decision_maker", "decision_role", "comments", "created_at"):
            self.assertIn(field, database.APPLICATION_SHORTLIST_DECISIONS_SCHEMA_SQL)
        self.assertIn("application_shortlist_audit", database.APPLICATION_SHORTLIST_AUDIT_SCHEMA_SQL)

    def test_application_count_sql_excludes_drafts(self):
        cursor = Mock()
        cursor.fetchone.return_value = (2,)
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            self.assertEqual(database.count_challenge_applications("GOV-APPLY-001"), 2)
        self.assertIn("status <> 'draft'", cursor.execute.call_args_list[-1].args[0])

    def test_screening_decision_insert_records_reviewer_and_comment(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("submitted",)
        connection = Mock()
        connection.cursor.return_value = cursor
        requirement = {"requirement": "Required skills: Python", "decision": "pass", "comment": "Verified"}
        with patch.object(database, "_open_connection", return_value=connection):
            database.save_application_screening("APP-1", "ministry-7", "ministry", [requirement])
        insert_call = cursor.execute.call_args_list[-1]
        self.assertIn("INSERT INTO application_screenings", insert_call.args[0])
        self.assertEqual(insert_call.args[1], ("APP-1", "ministry-7", "ministry", "Required skills: Python", "pass", "Verified"))
        connection.commit.assert_called_once()

    def test_eligibility_finalization_writes_status_and_audit_atomically(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("submitted",)
        cursor.rowcount = 1
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            finalized = database.finalize_application_screening(
                "APP-1", "ministry-7", "ministry", "eligible", {"requirements_reviewed": 3}
            )
        self.assertTrue(finalized)
        update_call = cursor.execute.call_args_list[-2]
        self.assertIn("UPDATE applications SET status = %s", update_call.args[0])
        self.assertEqual(update_call.args[1], ("eligible", "APP-1"))
        audit_call = cursor.execute.call_args_list[-1]
        self.assertIn("INSERT INTO application_screening_audit", audit_call.args[0])
        self.assertEqual(audit_call.args[1][1:4], ("ministry-7", "ministry", "eligibility_approved"))
        self.assertEqual(json.loads(audit_call.args[1][4]), {"requirements_reviewed": 3})
        connection.commit.assert_called_once()

    def test_ineligible_application_cannot_start_evaluation_at_database_layer(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("ineligible",)
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            started = database.start_application_evaluation(
                "APP-1", "ministry-7", "ministry", [{"criterion": "Impact", "description": "", "maximum_score": 100, "weight": 100, "required": True}]
            )
        self.assertFalse(started)
        self.assertFalse(any("UPDATE applications SET status = 'under_evaluation'" in call.args[0] for call in cursor.execute.call_args_list))
        connection.rollback.assert_called_once()

    def test_weighted_evaluation_total_is_calculated_from_score_and_maximum(self):
        total, maximum = database._evaluation_totals([
            (50, 100, 60),
            (4, 5, 40),
            (None, 100, 10),
        ])
        self.assertEqual(total, 62)
        self.assertEqual(maximum, 110)

    def test_evaluation_fallback_criteria_only_apply_when_challenge_has_none(self):
        challenge = {"evaluationCriteria": [{"criterion": "Challenge-specific criterion", "description": "Defined by government", "weight": 100}]}
        criteria = application_module._evaluation_criteria(challenge)
        self.assertEqual([item["criterion"] for item in criteria], ["Challenge-specific criterion"])
        self.assertEqual(criteria[0]["description"], "Defined by government")
        fallback = application_module._evaluation_criteria({"evaluationCriteria": []})
        self.assertIn("Problem Relevance", [item["criterion"] for item in fallback])
        self.assertNotEqual([item["criterion"] for item in fallback], [item["criterion"] for item in criteria])

    def test_database_completion_requires_required_scores_and_writes_status_audit(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("EVAL-1",)
        cursor.fetchall.return_value = [
            ("Technical Feasibility", 75, 100, 60, 1),
            ("Expected Impact", None, 100, 40, 0),
        ]
        cursor.rowcount = 1
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            totals = database.complete_application_evaluation("APP-1", "ministry-7", "ministry")
        self.assertEqual(totals, {"total_score": 45.0, "maximum_total_score": 100.0})
        updates = [call.args[0] for call in cursor.execute.call_args_list if "UPDATE " in call.args[0]]
        self.assertTrue(any("status = 'evaluation_complete'" in query for query in updates))
        self.assertTrue(any("status = 'evaluation_complete'" in query and "applications" in query for query in updates))
        self.assertTrue(any("INSERT INTO application_evaluation_audit" in call.args[0] for call in cursor.execute.call_args_list))
        connection.commit.assert_called_once()

    def test_database_completion_rejects_missing_required_score(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("EVAL-1",)
        cursor.fetchall.return_value = [("Technical Feasibility", None, 100, 60, 1)]
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "required criterion"):
                database.complete_application_evaluation("APP-1", "ministry-7", "ministry")
        self.assertFalse(any("UPDATE applications" in call.args[0] for call in cursor.execute.call_args_list))
        connection.rollback.assert_called_once()

    def test_database_shortlist_decision_updates_application_and_audits(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("evaluation_complete", "evaluation_complete")
        cursor.rowcount = 1
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            recorded = database.record_application_shortlist_decision(
                "APP-1", "shortlisted", "ministry-7", "ministry", "Ready for final selection."
            )
        self.assertTrue(recorded)
        decision_insert = next(call for call in cursor.execute.call_args_list if "INSERT INTO application_shortlist_decisions" in call.args[0])
        self.assertEqual(decision_insert.args[1][1:], ("APP-1", "shortlisted", "ministry-7", "ministry", "Ready for final selection."))
        self.assertTrue(any("UPDATE applications SET status = %s" in call.args[0] for call in cursor.execute.call_args_list))
        audit_insert = next(call for call in cursor.execute.call_args_list if "INSERT INTO application_shortlist_audit" in call.args[0])
        self.assertEqual(audit_insert.args[1][2:5], ("ministry-7", "ministry", "application_shortlisted"))
        self.assertEqual(json.loads(audit_insert.args[1][5]), {"decision": "shortlisted", "comments": "Ready for final selection."})
        connection.commit.assert_called_once()

    def test_database_shortlist_rejects_applications_not_evaluation_complete(self):
        cursor = Mock()
        cursor.fetchone.return_value = ("under_evaluation", "in_progress")
        connection = Mock()
        connection.cursor.return_value = cursor
        with patch.object(database, "_open_connection", return_value=connection):
            recorded = database.record_application_shortlist_decision(
                "APP-1", "not_selected", "ministry-7", "ministry", "Not ready."
            )
        self.assertFalse(recorded)
        self.assertFalse(any("INSERT INTO application_shortlist_decisions" in call.args[0] for call in cursor.execute.call_args_list))
        connection.rollback.assert_called_once()
