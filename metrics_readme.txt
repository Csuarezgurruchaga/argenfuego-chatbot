HYBRID CHATBOT · METRICS GUIDE (FOR STAKEHOLDERS)

What you will see in Google Sheets
1) METRICS_BUSINESS (KPIs for the business)
   • Granularity: daily rows (one row per day).
   • Columns (left → right):
     - date: YYYY-MM-DD (server timezone)
     - conversations_started: new conversations that day
     - conversations_finished: conversations closed that day
     - leads_sent: number of lead emails sent that day
     - human_requests: users who asked to talk to a human (friction proxy)
     - intent_presupuesto: conversations mapped to “Presupuesto”
     - intent_visita_tecnica: mapped to “Visita técnica”
     - intent_urgencia: mapped to “Urgencia”
     - intent_otras: mapped to “Otras”
     - geo_caba: addresses tagged as CABA
     - geo_provincia: addresses tagged as Provincia de Buenos Aires
     - messages_sent: number of messages sent (Meta status: sent)
     - messages_delivered: number of messages delivered (Meta status: delivered)
     - messages_failed: number of messages failed (Meta status: failed)
     - messages_undelivered: number of messages undelivered (Meta status: undelivered)
     - messages_read: number of messages read (Meta status: read)

   • How to read it:
     - Conversion proxy: leads_sent / conversations_started.
     - Intent mix: intent_* columns show demand distribution.
     - Friction proxy: human_requests help spot blockers.
     - Geo split: geo_caba vs geo_provincia can inform operations and coverage.
     - Message delivery: messages_delivered / messages_sent shows delivery success rate.
     - Engagement: messages_read / messages_delivered shows user engagement rate.

2) METRICS_TECH (operational health)
   • Granularity: daily rows (one row per day).
   • Columns:
     - date: YYYY-MM-DD
     - nlu_unclear: cases where the system could not map the user intent
     - exceptions: technical errors captured (e.g., webhook/SES/Meta/OpenAI)
     - validation_fail_email: failed email validations (count)
     - validation_fail_direccion: failed address validations (count)
     - validation_fail_horario_visita: failed schedule validations (count)
     - validation_fail_descripcion: failed description validations (count)

   • How to read it:
     - nlu_unclear: if high, improve patterns/prompts or examples.
     - exceptions: investigate spikes (infrastructure or provider issues).
     - validation_fail_*: high counts indicate UX issues in form validation.

3) ERRORS (event log – troubleshooting)
   • Granularity: one row per event (not aggregated).
   • Fields include: timestamp, env, company, trigger_type, (anon) conversation id,
     masked phone, previous_state → current_state, short NLU/validation snapshots,
     and a recommended_action.
   • Use this to drill down into specific incidents or friction points.

Update cadence and limits
• Metrics are cached in-memory and flushed to Sheets periodically.
• Default flush window is 3600 seconds (1 hour), configurable via METRICS_FLUSH_SECONDS.
• Errors are logged to ERRORS immediately (best-effort), with rate limiting and deduping.
• Optional email alerts for high-severity events if ENABLE_ERROR_REPORTS=true.

Common interpretations
• Demand: track intent_* to see what users ask for. Align staffing and inventory.
• Performance: leads_sent rising with flat conversations_started = better conversion.
• Funnel friction: high human_requests implies UX/content fixes.
• Geography: geo_caba vs geo_provincia mix supports routing/logistics decisions.
• Reliability: sustained exceptions require provider (Meta) or infra review.
• Message delivery: low delivery rates may indicate WhatsApp Cloud API issues.
• User engagement: low read rates may indicate message timing or content issues.
• Validation issues: high validation_fail_* in TECH metrics indicate form UX problems.

Operational tips
• Use daily rollups for trends; use ERRORS for individual cases.
• Avoid storing PII: phones/emails are masked in ERRORS and not present in KPIs.
• Keep tab names consistent: METRICS_BUSINESS, METRICS_TECH, ERRORS.

Environment variables (for reference)
• ENABLE_SHEETS_METRICS=true
• SHEETS_METRICS_SPREADSHEET_ID=<your_sheet_id>
• SHEETS_BUSINESS_SHEET_NAME=METRICS_BUSINESS
• SHEETS_TECH_SHEET_NAME=METRICS_TECH
• SHEETS_ERRORS_SHEET_NAME=ERRORS
• GOOGLE_SERVICE_ACCOUNT_JSON=<service_account_json (base64 or raw)>
• METRICS_FLUSH_SECONDS=3600 (recommended for low traffic)
• (Optional) ENABLE_ERROR_REPORTS=true and ERROR_LOG_EMAIL=<dev_email>

FAQ
• Why some days have zeros? No traffic or the service was idle.
• Can we change granularity? Yes, we can add hourly sheets or per-intent tabs later.
• Can we export to BI tools? Yes, Sheets can be connected to Data Studio/Looker.
