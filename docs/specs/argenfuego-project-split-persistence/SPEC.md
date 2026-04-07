# SPEC

## Title
Argenfuego project split plus persistent runtime state

## Summary
Move Argenfuego to its own GCP project named `argenfuego` and add persistent runtime state so the chatbot survives Cloud Run scale-to-zero. The persistent runtime model must follow the proven Kleiman architecture for bot checkpoints plus persisted handoff inbox state, while explicitly excluding the backoffice UI and Firebase auth surface.

## Goals
- Deploy `argenfuego-chatbot` into a dedicated GCP project `argenfuego`.
- Persist resumable bot state in Firestore.
- Persist human handoff state in Firestore, including queue/case ordering and message history needed to survive instance loss.
- Keep the current WhatsApp webhook and agent-via-WhatsApp operational model.
- Preserve a low-cost serverless footprint.

## Non-Goals
- Port the Kleiman backoffice UI or Firebase auth.
- Migrate historical chat state from the existing shared project.
- Redesign the current Argenfuego conversational flow.
- Migrate the shared dispatcher out of its current project in this initiative.

## Product Decisions
- New GCP project: `argenfuego`.
- New Firestore database: the project default native database `"(default)"` in `southamerica-west1`.
- Runtime persistence scope: bot checkpoints plus persisted handoff inbox, without backoffice.
- Validation path: use the Kleiman testing number first by temporarily rerouting that number in the shared dispatcher to the new `argenfuego-chatbot`.
- Final cutover: after validation passes, load the real Argenfuego secrets in the new project and repoint the real Argenfuego dispatcher route.

## Functional Requirements
1. The webhook must still accept the current `GET/POST /webhook/whatsapp` contract.
2. Resumable bot states must survive process loss and be rehydrated on demand.
3. Duplicate inbound Meta messages must be deduped using persisted `message_id`.
4. Handoff state must survive process loss, including active case, queued cases, inbound messages, agent replies, and queue ordering.
5. Handoff closures must support both inactivity-based autoclose and retention purge.
6. The current agent-driven WhatsApp workflow must keep working without a backoffice.

## Data Model
- Firestore collection `conversation-checkpoints`
- Firestore collection `processed-inbound-message-ids`
- Firestore collection `handoff_inbox_cases`
- Firestore subcollections `messages` and `outbox` under each handoff case

## Runtime Configuration
- Introduce generic env vars for runtime persistence and purge behavior.
- Do not reuse Kleiman-specific names such as `EXPENSAS_*`.
- Keep existing Argenfuego runtime env vars for Meta, Sheets, surveys, and email unless a new generic name is needed for persistence.

## Internal Endpoints
- `POST /session-checkpoints/cleanup`
- `POST /internal/handoff/autoclose`
- `POST /internal/handoff/purge`

## Operational Requirements
- New Cloud Scheduler jobs must exist in the `argenfuego` project for checkpoint cleanup, handoff autoclose, and handoff retention purge.
- The existing shared dispatcher remains the routing layer for both testing and final cutover.
- The old shared-project `argenfuego-chatbot` remains available as rollback during cutover.
