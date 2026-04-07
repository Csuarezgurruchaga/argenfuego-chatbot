# CHECKPOINT

- Branch: `impl/argenfuego-project-split-persistence`
- Spec slug: `argenfuego-project-split-persistence`
- Current task: `T7`
- Next implementation focus:
  - validate the new `argenfuego-chatbot` service using the Kleiman testing number through the shared dispatcher
  - confirm checkpoint persistence and handoff recovery against the new Firestore-backed runtime
  - only after that, switch the service to real Argenfuego secrets and cut over the real dispatcher route
