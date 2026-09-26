"""Load demo data for testing StartupConnect end to end.

Usage (MySQL must be configured as for the app):

    python seed_demo.py            # demo startups + demo challenge + applications
    python seed_demo.py --accounts # demo startups only

Safe to run repeatedly: anything that already exists is left unchanged.
All organisations, people and identifiers are fictional.
"""

import sys

import app as application_module
from database import DEMO_STARTUPS, DuplicateApplicationError, get_startup_application, save_application, seed_demo_startups

DEMO_CHALLENGE_ID = "GOV-DEMO-001"
DEMO_MINISTRY_ID = "admin"

DEMO_CHALLENGE = {
    "id": "gov-demo-001",
    "challengeId": DEMO_CHALLENGE_ID,
    "title": "Multilingual citizen grievance triage for urban local bodies",
    "template": "ai",
    "category": "Governance",
    "categoryList": ["Governance", "AI / ML"],
    "challengeType": "Software",
    "difficulty": "Advanced",
    "status": "start bidding",
    "createdBy": DEMO_MINISTRY_ID,
    "ministry": "Maharashtra State Innovation Society",
    "department": "Department of Skills, Employment, Entrepreneurship and Innovation",
    "state": "Maharashtra",
    "assignedStartupId": None,
    "bids": [],
    "bidStartPrice": 0,
    "currentBidPrice": 0,
    "isDemo": True,
    "problemStatement": {
        "description": "Municipal corporations receive thousands of citizen grievances every week by phone, WhatsApp, web forms and walk-ins, largely in Marathi and Hindi. Complaints are logged manually, routed to the wrong ward office about a third of the time, and take a median of 72 hours to reach the officer who can act.",
        "currentSituation": "Call-centre staff re-type complaints into a legacy portal and assign departments by hand. There is no single view of pending grievances or SLA breaches.",
        "painPoints": ["Manual re-entry and mis-routing", "No SLA visibility for ward officers", "Citizens receive no status updates"],
        "affectedGroups": ["Citizens", "Ward officers", "Municipal commissioners"],
        "geographicScope": "Urban local bodies in Maharashtra",
        "impact": "Faster, correctly routed grievance resolution and measurable citizen satisfaction.",
    },
    "objectives": {"primary": "Cut grievance routing and resolution time using multilingual intake and automatic triage.", "secondary": ["Give ward officers an SLA dashboard", "Send citizens status updates"]},
    "expectedOutcomes": [
        {"text": "Median time to reach the responsible officer under 12 hours", "order": 1},
        {"text": "Routing accuracy above 90%", "order": 2},
        {"text": "Citizen satisfaction above 75%", "order": 3},
    ],
    "requirements": {
        "mandatory": [
            "Marathi, Hindi and English voice and text intake",
            "Automatic categorisation and routing to the responsible department",
            "Role-based access for ward officers",
            "Resolution tracking dashboard with SLA alerts",
        ],
        "optional": ["WhatsApp channel", "Integration with the existing grievance portal"],
        "features": [{"name": "Citizen status notifications", "priority": "Mandatory"}],
    },
    "constraints": {"technical": ["Hosted on MeghRaj / state data centre", "Personal data stays in India"], "budget": {"estimatedBudget": "₹25,00,000 for a 3-month pilot", "budgetType": "Indicative"}},
    "eligibility": {"participantTypes": ["Startups"], "minTeamSize": "3", "maxTeamSize": "60", "requiredSkills": ["Speech and language AI", "Government software delivery"]},
    "selectionConfiguration": {"maximumSelectedStartups": 2},
    "timeline": {"registrationOpen": "2026-09-01", "registrationClose": "2027-03-15", "submissionOpen": "2026-09-01", "submissionDeadline": "2027-03-31", "evaluationStart": "2027-04-01", "resultsDate": "2027-04-30"},
    "evaluationCriteria": [
        {"criterion": "Problem fit", "description": "Addresses multilingual intake, routing and SLA tracking", "weight": 25, "maximumScore": 10},
        {"criterion": "Technical feasibility", "description": "Accuracy, architecture and data-residency approach", "weight": 25, "maximumScore": 10},
        {"criterion": "Deployment readiness", "description": "Evidence of working deployments", "weight": 20, "maximumScore": 10},
        {"criterion": "Measurable impact", "description": "Quantified, verifiable outcomes", "weight": 20, "maximumScore": 10},
        {"criterion": "Team capability", "description": "Relevant delivery experience", "weight": 10, "maximumScore": 10, "required": False},
    ],
    "createdAt": "2026-09-01T09:00:00Z",
    "updatedAt": "2026-09-26T09:00:00Z",
}

# Five applications of deliberately different quality, so screening, pre-assessment,
# panel scoring and pilots all have something meaningful to show.
DEMO_APPLICATIONS = {
    "bhashamitra": {  # strongest: deployed, quantified, covers every requirement
        "problem_addressed": "Grievances in Marathi and Hindi are re-typed by hand and mis-routed, delaying action by days.",
        "challenge_solution": "BhashaMitra Seva: a multilingual voice and text intake layer with automatic categorisation and routing to the responsible department, plus a ward officer dashboard with SLA alerts and citizen status notifications.",
        "solution_description": "Citizens call a helpline or send a WhatsApp voice note in Marathi, Hindi or English. Our speech recognition transcribes the complaint, a classifier trained on 1.4 lakh historical municipal grievances assigns category and ward, and the complaint is routed automatically to the responsible department. Ward officers work from a role-based dashboard that shows pending items, SLA timers and escalations. Citizens receive SMS and WhatsApp status notifications at each step.",
        "technology_approach": "Fine-tuned open-source speech models for Marathi and Hindi, a transformer text classifier for categorisation and routing, and a Django dashboard with role-based access for ward officers. Everything runs on the state data centre so personal data stays in India. We expose REST APIs to integrate with the existing grievance portal and can run fully on-premise.",
        "development_stage": "Deployed in production with Satara Municipal Council since January 2025; pilot running in two Pune wards.",
        "implementation_approach": "Weeks 1-3: deploy in four wards and record baseline resolution times. Weeks 4-8: tune routing on local data, train 60 ward officers, enable SLA alerts. Weeks 9-12: measure outcomes against baseline and prepare the scale-up plan. A dedicated delivery manager sits with the corporation's IT cell throughout.",
        "expected_timeline": "12 weeks in three phases: deploy (3 weeks), tune and train (5 weeks), measure (4 weeks).",
        "government_support": "Access to 12 months of anonymised historical grievances, ward officer nominations, and a VM on the state data centre.",
        "expected_outcomes": "Grievances reach the responsible officer in under 12 hours instead of 72, routing accuracy above 90%, every citizen receives status notifications, and commissioners get a live SLA dashboard for all wards. We expect the corporation to be able to scale to all wards within one quarter after the pilot, with costs falling as call-centre re-entry is removed.",
        "target_users": "Citizens, call-centre staff, ward officers and municipal commissioners.",
        "measurable_impact": "In Satara we cut median routing time from 68 to 9 hours (87% faster) and raised routing accuracy from 64% to 93% across 41,000 grievances in 9 months; citizen satisfaction rose from 48% to 79%.",
        "previous_deployments": "Satara Municipal Council (production, 2025); Pune Municipal Corporation, 2 wards (pilot, 2026).",
        "relevant_experience": "Founding team built speech products at a national language-technology mission and has delivered three government software projects with state data-centre hosting and CERT-In empanelled security audits.",
        "supporting_evidence": "Satara impact report (PDF), CERT-In audit certificate 2025, letter of appreciation from the Chief Officer, https://bhashamitra.example/case-study",
        "additional_information": "",
    },
    "sahajseva": {  # solid: strong on access and officers, weaker on AI routing evidence
        "problem_addressed": "Citizens who cannot use web forms depend on staff to register complaints, and complaints are not tracked after registration.",
        "challenge_solution": "Assisted intake at citizen service centres and a helpline in Marathi, Hindi and English, with rule-based categorisation, routing to departments, role-based access for ward officers and an SLA tracking dashboard.",
        "solution_description": "SahajSeva kiosks and operator software let staff capture voice and text complaints in three languages with accessibility features for elderly and visually impaired citizens. Complaints are categorised by a rules engine and routed to the responsible department. Ward officers use a role-based dashboard with SLA alerts, and citizens receive SMS status notifications with a tracking number.",
        "technology_approach": "Progressive web app for kiosks and operators, cloud speech-to-text for intake, a configurable rules engine for categorisation and routing, and PostgreSQL on the state data centre. Role-based access control with audit logs for every status change.",
        "development_stage": "Pilot running in 6 citizen service centres in Mumbai suburban district.",
        "implementation_approach": "Install at 10 service centres, configure routing rules with each department, train operators and ward officers, then run a 10-week measured pilot with fortnightly reviews with the corporation.",
        "expected_timeline": "3 months: 2 weeks setup, 10 weeks measured pilot.",
        "government_support": "Space and power at service centres, department contact lists for routing rules, and nominated nodal officers.",
        "expected_outcomes": "Every complaint receives a tracking number and status notifications, assisted citizens can register complaints in their language, and ward officers see pending items against SLA. We expect a clear drop in mis-routed complaints once routing rules are tuned with departments during the pilot.",
        "target_users": "Citizens needing assisted access, service centre operators and ward officers.",
        "measurable_impact": "At 6 centres, 11,200 complaints registered in 5 months; 96% received an SMS tracking number; average registration time fell from 14 to 6 minutes.",
        "previous_deployments": "Mumbai suburban district citizen service centres (pilot, 2025-26).",
        "relevant_experience": "Team has delivered accessibility-compliant kiosks for two state departments and follows GIGW accessibility guidelines.",
        "supporting_evidence": "District collector's pilot report, GIGW compliance report.",
        "additional_information": "Routing accuracy for AI-based classification has not yet been measured; we propose measuring it during this pilot.",
    },
    "kachrasetu": {  # adequate: adjacent domain, partial requirement coverage
        "problem_addressed": "Sanitation complaints are the largest category of municipal grievances and are handled slowly.",
        "challenge_solution": "Extend our waste-monitoring platform to take citizen sanitation complaints and route them to ward sanitation officers with SLA alerts.",
        "solution_description": "KachraSetu already monitors garbage points with cameras and optimises collection routes. We would add a complaint intake app in English and Marathi so citizens can report garbage and drainage issues with photos. Complaints are matched to the nearest collection route and sent to the ward sanitation officer, who sees them on our existing dashboard with SLA alerts.",
        "technology_approach": "Computer vision for garbage detection, a mobile app for citizen intake with photo upload, and our existing officer dashboard. Hosted on a commercial cloud in the Mumbai region.",
        "development_stage": "Deployed for waste monitoring in Thane; complaint intake is at prototype stage.",
        "implementation_approach": "Launch the citizen app in 3 wards, connect it to the existing sanitation dashboard, and review SLA performance monthly.",
        "expected_timeline": "4 months",
        "government_support": "Ward sanitation officer contacts and publicity for the citizen app.",
        "expected_outcomes": "Faster resolution of sanitation complaints and better visibility for ward sanitation officers.",
        "target_users": "Citizens and ward sanitation officers.",
        "measurable_impact": "Garbage point overflow incidents fell 38% in Thane pilot wards.",
        "previous_deployments": "Thane Municipal Corporation, waste monitoring (production).",
        "relevant_experience": "Five years of municipal solid-waste technology projects.",
        "supporting_evidence": "Thane deployment report.",
        "additional_information": "",
    },
    "netrascan": {  # off-target: strong company, wrong problem
        "problem_addressed": "Citizens face delays getting health services.",
        "challenge_solution": "Use our AI screening platform to prioritise health-related grievances.",
        "solution_description": "NetraScan runs AI retinal screening in primary health centres. We can adapt our triage engine to flag urgent health complaints so they are handled first by the health department.",
        "technology_approach": "Deep learning triage models and a clinician dashboard.",
        "development_stage": "Deployed in 40 primary health centres for retinal screening.",
        "implementation_approach": "Adapt the triage engine to grievance text and share a dashboard with the health department.",
        "expected_timeline": "6 months",
        "government_support": "Access to health grievance data.",
        "expected_outcomes": "Urgent health complaints handled faster.",
        "target_users": "Health department officers.",
        "measurable_impact": "Screened 52,000 patients for diabetic retinopathy with 91% sensitivity.",
        "previous_deployments": "40 PHCs in Pune district.",
        "relevant_experience": "Medical AI with CDSCO-registered device.",
        "supporting_evidence": "Peer-reviewed validation study.",
        "additional_information": "",
    },
    "poshantrack": {  # weak: idea stage, unquantified, thin answers
        "problem_addressed": "Complaints are not handled well.",
        "challenge_solution": "An app for complaints.",
        "solution_description": "We will build a mobile app where citizens can post complaints and officers can reply.",
        "technology_approach": "Mobile app and cloud backend.",
        "development_stage": "Idea stage, team formed.",
        "implementation_approach": "Build the app and launch it.",
        "expected_timeline": "To be decided",
        "government_support": "Funding and data.",
        "expected_outcomes": "Better complaint handling.",
        "target_users": "Citizens.",
        "measurable_impact": "Improved satisfaction.",
        "previous_deployments": "None",
        "relevant_experience": "Students with app development experience.",
        "supporting_evidence": "",
        "additional_information": "",
    },
}


def seed_demo_challenge():
    store = application_module._read_store()
    if any(item.get("challengeId") == DEMO_CHALLENGE_ID for bucket in ("drafts", "published") for item in store.get(bucket, {}).values()):
        return False
    store["published"][DEMO_CHALLENGE["id"]] = dict(DEMO_CHALLENGE)
    application_module._write_store(store)
    return True


def seed_demo_applications():
    submitted = 0
    for business_id, answers in DEMO_APPLICATIONS.items():
        if get_startup_application(DEMO_CHALLENGE_ID, business_id):
            continue
        data = {key: str(answers.get(key, "")) for key in application_module.APPLICATION_FIELDS}
        try:
            save_application(DEMO_CHALLENGE_ID, business_id, data, "submitted")
            submitted += 1
        except DuplicateApplicationError:
            continue
    return submitted


def main(argv):
    added = seed_demo_startups()
    print(f"Demo startups: {added} added, {len(DEMO_STARTUPS) - added} already present.")
    if "--accounts" not in argv:
        print("Demo challenge GOV-DEMO-001:", "created" if seed_demo_challenge() else "already present")
        print(f"Demo applications: {seed_demo_applications()} submitted.")
    print("\nSign in at /login. Credentials are listed in DEMO_ACCOUNTS.md.")


if __name__ == "__main__":
    main(sys.argv[1:])
