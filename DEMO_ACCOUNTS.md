# Demo accounts for testing

All organisations, people, CIN and GSTIN numbers are **fictional**. The GSTINs are well-formed (correct check character) but belong to no one. Websites use the reserved `.example` domain.

## Startup logins

Sign in at `/login` → **Startup** tab. Startups sign in with all three fields.

| Startup | Business ID | GSTIN | Password | Sector | Role in the demo scenario |
|---|---|---|---|---|---|
| FieldSense Innovations | `demo-startup-mh` | `27AAAAA0000A1Z5` | `DemoStartup@123` | Agriculture | No application yet: use it to apply yourself |
| NetraScan Health | `netrascan` | `27AAHCN4821K1Z8` | `NetraScan@2026` | Health-tech | Off-target application: strong company, wrong problem |
| JalRakshak Technologies | `jalrakshak` | `27AAHCJ7314M1Z6` | `JalRakshak@2026` | Climate-tech | No application yet: use it to apply yourself |
| SahajSeva Digital | `sahajseva` | `27AAHCS2209P1ZZ` | `SahajSeva@2026` | Gov-tech | Solid application: good access and officer tools, weaker AI evidence |
| GatiFlow Mobility | `gatiflow` | `27AAHCG5567Q1ZQ` | `GatiFlow@2026` | Mobility | No application yet: use it to apply yourself |
| PoshanTrack Labs | `poshantrack` | `27AAHCP8834R1ZF` | `PoshanTrack@2026` | Health-tech | Weak application: idea stage, unquantified, thin answers |
| BhashaMitra AI | `bhashamitra` | `27AAHCB3390S1ZY` | `BhashaMitra@2026` | AI / ML | Strongest application: deployed, quantified, covers every requirement |
| KachraSetu CleanTech | `kachrasetu` | `27AAHCK6178T1ZF` | `KachraSetu@2026` | Smart City | Adequate application: adjacent domain, partial coverage |

## Ministry login

Sign in at `/login` → **Ministry** tab.

| Ministry ID | Auth code | Notes |
|---|---|---|
| `admin` | `1234` | Owns the demo challenge `GOV-DEMO-001` and the existing challenge `GOV-2026-00001` |

## Loading the demo data

The eight startup accounts are created automatically the first time the app talks to MySQL (a login, or opening the startup directory).

To also load the ready-made test scenario (one challenge and five submitted applications), run once:

```
python seed_demo.py
```

This creates **GOV-DEMO-001, "Multilingual citizen grievance triage for urban local bodies"**. It is owned by `admin`, allows at most 2 selected startups, and has applications from BhashaMitra, SahajSeva, KachraSetu, NetraScan and PoshanTrack. JalRakshak, GatiFlow and FieldSense have not applied, so you can test the application form with them.

Running it again changes nothing. Use `python seed_demo.py --accounts` to create only the startup accounts.

## Suggested test walkthrough

1. **Ministry:** go to Government dashboard → GOV-DEMO-001 → Applications. Screen BhashaMitra and SahajSeva as eligible; mark PoshanTrack ineligible or request clarification.
2. **Advanced evaluation:** open "Panel & risk evaluation" on each eligible application. The automatic first check should rate BhashaMitra *Strong* and PoshanTrack *Weak*. Add three panelist scorecards, one with a declared conflict, then a risk assessment and a financial proposal.
3. **Scorecard and shortlist:** complete the standard evaluation, shortlist both, then confirm the final selection (for example, select BhashaMitra only).
4. **Pilot:** go to Sandbox & pilots → set up a pilot for BhashaMitra → fill in and send the agreement.
5. **Startup:** sign in as BhashaMitra → portal → "Review pilot agreement" → accept it (or request changes first).
6. **Ministry:** complete the readiness checks → Go live.
7. **Startup:** submit a progress report with KPI readings, a milestone claim, and optionally a Critical incident to see the suspension warning.
8. **Ministry:** verify the readings and the milestone, release the payment, start the results review, and record the board decision.

## Settings

| Environment variable | Default | Effect |
|---|---|---|
| `STARTUP_CONNECT_DEMO_MODE` | `false` | When `true`, the login page lists the demo accounts with one-click fill. **Never enable in production.** |
| `STARTUP_CONNECT_SEED_DEMO_DATA` | `true` | Set to `false` to stop creating the demo startup accounts. Set it for any real deployment. |
