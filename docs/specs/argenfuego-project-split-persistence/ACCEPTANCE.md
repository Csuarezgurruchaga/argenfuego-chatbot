# ACCEPTANCE

## Software
- Bot checkpoints are saved, loaded, expired, and deleted correctly.
- Duplicate inbound messages are ignored after the first persisted processing.
- A handoff case can be created, reopened from persistence, replied to, auto-closed, and purged without a backoffice.
- A cold runtime can reconstruct active and queued handoff state from Firestore.

## Infrastructure
- A new GCP project `argenfuego` exists with Cloud Run, Firestore, Secret Manager, and Scheduler enabled.
- The new `argenfuego-chatbot` service is deployed in `southamerica-west1`.
- Three scheduler jobs exist and can be run manually:
  - session checkpoint cleanup
  - handoff autoclose
  - handoff retention purge

## Validation
- The new service passes focused pytest coverage for persistence and handoff runtime restoration.
- The new service is validated end-to-end using the Kleiman testing number after temporary dispatcher reroute.
- After final cutover, the real Argenfuego route points to the new project and the old service is no longer serving traffic.
