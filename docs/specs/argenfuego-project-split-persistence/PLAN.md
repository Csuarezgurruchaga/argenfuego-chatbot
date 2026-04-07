# PLAN

## Implementation Strategy
1. Add a spec package and implement the runtime persistence slice inside `hybrid-chatbot`.
2. Port the Kleiman checkpoint service and handoff inbox service using generic names and only the runtime behaviors Argenfuego needs.
3. Wire the new persistence layer into `chatbot/states.py`, `chatbot/models.py`, and `main.py`.
4. Add focused tests that prove checkpoint hydration, handoff persistence, dedupe, autoclose, and retention behavior.
5. Bootstrap the new GCP project `argenfuego`, deploy the new service there, and create the supporting scheduler jobs.
6. Validate end-to-end with the Kleiman testing number by temporarily rerouting that dispatcher entry to the new service.
7. Replace the testing secrets with the real Argenfuego secrets in the new project and cut the real dispatcher route over.

## Key Design Notes
- Firestore is the runtime authority for resumable bot state and persisted handoff state.
- In-memory state remains as an optimization, not the source of truth.
- Persisted handoff state must be sufficient to reconstruct queue ordering and the active case after a cold start.
- The implementation must not introduce backoffice-only abstractions into Argenfuego.
- The new GCP project must be standalone for service, secrets, Firestore, and schedulers.

## Rollout Shape
- Stage 1: software port + local verification.
- Stage 2: new-project bootstrap + first deploy using testing secrets.
- Stage 3: dispatcher-based testing with the Kleiman number.
- Stage 4: final Argenfuego secrets + final dispatcher cutover.

## Rollback
- If stage 2 fails, keep all traffic on the existing shared-project Argenfuego service.
- If stage 3 fails, restore the Kleiman testing route in the dispatcher immediately.
- If stage 4 fails, restore the Argenfuego dispatcher route to the old service and keep the new project available for debugging.
