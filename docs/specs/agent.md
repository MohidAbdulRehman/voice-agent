# Voice agent spec

Python, LiveKit Agents, under `src/intake/agent/`. **Before writing any LiveKit code, look up the current API with the `livekit-docs` MCP server** (and the `livekit-examples/agent-starter-python` template). This spec describes *behavior*; exact class and parameter names must come from current docs, not memory.

## 1. Architecture choices (deliberate; keep them)

- **One `Agent` with a fixed tool list for the whole call.** Adding or removing tools mid-call is not allowed. It's simpler, has fewer failure modes, and is easier to explain. Handoffs are listed as a README "Next Step".
- **Pipeline:** speech-to-text → LLM → text-to-speech, not a realtime speech-to-speech model. Registration needs exact spellings, and a separate transcriber is easier to inspect and tune.
- **Tools call `intake.core` services directly**, in-process, and never the REST API. The assessment allows "or directly invoke the same service layer". Live calls therefore don't depend on the API's serverless function, and the agent keeps its own connection pool on Supabase's session pooler (port 5432).
- **Tools return structured facts, never sentences.** The LLM phrases everything; `core/speech.py` supplies exact spoken forms for the read-back.

## 2. Session wiring

| Concern | Requirement |
|---|---|
| Dispatch | Explicit dispatch as `AGENT_NAME` (`patient-intake`), matching the LiveKit dispatch rule. LiveKit Agents 1.8 reads the name from `LIVEKIT_AGENT_NAME` (its `agent_name=` argument is deprecated), so the server exports `AGENT_NAME` there before registering. |
| STT | Deepgram `nova-3` in multilingual mode (English/Spanish code-switching). Enable smart formatting and numerals if supported. Keyterm hints: clinic name, "Decline to Answer". |
| LLM | Fallback adapter: **primary** LiveKit Inference `LLM_PRIMARY_MODEL` (`openai/gpt-4.1-mini`), **fallback** Groq `LLM_FALLBACK_MODEL` (`llama-3.3-70b-versatile`). Temperature 0.3. Disable parallel tool calls if the plugin allows it. |
| TTS | Fallback adapter: **primary** Cartesia `sonic-3` with `CARTESIA_VOICE_EN`, **fallback** Deepgram Aura-2 with `DEEPGRAM_TTS_VOICE_EN`. `set_language` switches both to the Spanish voice and language (`CARTESIA_VOICE_ES`, `DEEPGRAM_TTS_VOICE_ES`). If no Aura-2 Spanish voice is configured, the fallback stays English; document this. |
| Turn-taking | Silero VAD plus LiveKit's turn-detector model, so the agent doesn't jump in while someone pauses mid-phone-number. Callers can interrupt the agent (the default). In LiveKit Agents 1.8 both are built in: the session's default VAD is the bundled Silero model, and `inference.TurnDetector()` is the audio end-of-turn model (English and Spanish, among 14 languages). The older text model, `MultilingualModel` from the turn-detector plugin, is deprecated, so neither plugin is needed. |
| Noise | Telephony-optimized noise cancellation for SIP participants, if the plan supports it. Skip it gracefully if not. Implemented with `livekit-plugins-noise-cancellation`, as a per-participant selector in the room input options: SIP callers get `BVCTelephony()`, Krisp's telephony voice isolation, which is metered (the Build plan includes 100 minutes a month, twice the 50 phone minutes); anyone else gets `NC()`, background noise suppression, which is free. It runs only on audio that comes through LiveKit Cloud, so not in console mode. |
| Background audio | Office ambience at low volume, plus keyboard typing as the "thinking" sound during tool calls, so saves sound like typing rather than dead air. Implemented with `BackgroundAudioPlayer`: `OFFICE_AMBIENCE` at 0.4 for the whole call, and `KEYBOARD_TYPING`/`KEYBOARD_TYPING2` at 0.7 as the thinking sound. LiveKit plays the thinking sound whenever the agent is thinking, which includes tool calls. There's no room in console mode, so there's no background audio either. If it fails to start, the call goes on without it. |
| Greeting | Fixed text via `say`, not LLM-generated (faster, cheaper, deterministic). It must name the clinic and say "virtual assistant". The first sentence can't be interrupted. See §6. |
| Prompt | `prompts/system_prompt.md`. The loader strips `<!-- … -->` comments, then fills `{{agent_name}} {{clinic_name}} {{today}} {{timezone}} {{caller_line}}`. The loader writes `caller_line` itself: a US caller number as spoken digits followed by the "best number" question, or a request for the phone number when there's no number or it isn't a US one. `today` is computed in `CLINIC_TIMEZONE`, e.g. "Thursday, September 24, 2026". |
| Caller ID | Read from the SIP participant's attributes (check the current key in LiveKit's SIP participant reference). Store it on the `calls` row; show it to the LLM as spoken digits, or say there's no number (see Prompt). |
| Silence | After about 12 s of caller silence, say "Are you still there?". After a second silence, say a polite goodbye and call `end_call(no_response)`. |
| Call length cap | At `MAX_CALL_MINUTES` (default 12), the agent wraps up politely: it finishes if confirmed, otherwise it says staff will follow up. This protects the free minutes. |
| Metrics | Log LLM, STT and TTS latency metrics per turn (debug level), plus a per-call summary line (info). |
| Recording | For listening back to calls. `session.start` leaves `record` unset, so the LiveKit Cloud project's **Agent observability** setting (Settings → Data and privacy) decides: when it's on, each call's audio (caller and agent), transcript, traces and logs are uploaded after the call to the **Agent insights** tab of the Sessions page, for playback or download; LiveKit deletes them after 30 days. In console mode, `--record` saves `console-recordings/session-<time>/audio.ogg` (stereo: caller left, agent right) and `session_report.json` locally; that folder is git-ignored. |

## 3. Session state (`userdata`)

```python
@dataclass
class CallState:
    call_id: UUID                 # calls row created at session start
    channel: Literal["phone", "web", "console"]
    caller_number: str | None     # 10 digits if US, else raw
    language: Literal["English", "Spanish"] = "English"
    mode: Literal["create", "update"] = "create"
    target_patient_id: UUID | None = None        # set when caller chooses "update"
    duplicate_acknowledged: bool = False         # caller said "no, create a new record"
    draft: Draft | None = None                   # latest prepared draft (only one is valid)
    committed_patient_id: UUID | None = None
    commit_failures: int = 0
    offered_slots: dict[str, SlotRef] = field(default_factory=dict)  # opaque slot_id -> (doctor_id, start)
    appointment_id: UUID | None = None
    silence_prompts: int = 0
    matched_patient_id: UUID | None = None       # the latest found lookup (most recently updated match)
    saved: tuple[str, dict] | None = None        # (draft_id, result) of the successful commit
    end_reason: str | None = None                # set by end_call (or the time limit); the first one wins
```

After a successful create, `mode` becomes `update` with the new patient as the target, so a correction later in the same call updates that record (the call stays `registered`).

## 4. Tool contracts

Rules for every tool:
- It returns a JSON-serializable dict with a `status` key.
- It never raises to the LLM: exceptions become `{"status": "system_error"}` and are logged with a stack trace.
- It never exposes internal ids in anything meant to be spoken.
- Latency target: under 800 ms at the 95th percentile.
- The LLM receives the result as JSON (`str()` of a dict subclass), and every call logs `tool.called`.
- Beyond the results below, a tool refuses what can't be done yet with `{"status": "invalid", "errors": [{"field": null, "code", "message"}]}`: for example `prepare_record` with `no_patient_to_update`, `updating_existing_record` or `already_registered`.

### `lookup_patient_by_phone(phone_number: str)`
Normalizes the number and finds patients that are **not soft-deleted**. The agent calls it right after it gets the phone number.
```json
{"status": "found", "patient": {"first_name": "Jane", "last_name": "Doe"}, "match_count": 1}
{"status": "not_found"}
{"status": "invalid", "errors": [{"field": "phone_number", "code": "invalid_phone", "message": "…"}]}
{"status": "system_error"}
```
Side effect: remembers the matched `patient_id` in state (the most recently updated match if several). The LLM never sees the id.

### `prepare_record(action: "create" | "update", fields: PatientFields)`
`PatientFields` contains every patient field, all optional, in agent-friendly formats: `date_of_birth` as `MM/DD/YYYY`, and `state` as a code or full name.
- **create:** validates the full record.
  - Missing required fields: `{"status": "incomplete", "missing": ["zip_code"], "errors": [...]}`. Errors may also be present.
  - Invalid fields only: `{"status": "invalid", "errors": [...]}`.
  - Phone matches an active patient and the caller hasn't acknowledged it: `{"status": "duplicate", "patient": {"first_name", "last_name"}}`.
- **update:** requires a prior `found` lookup that the caller chose to update. `fields` holds **only the changes**.
- **ok:** `{"status": "ok", "draft_id": "d-7f3a", "readback": [{"group": "name", "spoken": "Jane Davis, that's D-A-V-I-S"}, …]}`.
  - `readback` groups and spoken forms come from `core/speech.py`, in `state.language`.
  - It's always the full read-back. After a correction, the agent reads out only the groups that changed. The tool doesn't trim the list, because the model sometimes calls `prepare_record` just to check the details without reading anything out; a trimmed read-back could then leave the caller never hearing some of the details before they're saved.
  - Every call creates a new draft and **invalidates earlier drafts**.
- Side effect: writes the normalized data to `calls.final_payload` (status stays `in_progress`), so an abandoned call still leaves a trace.

### `acknowledge_duplicate(choice: "update" | "create_new")`
The caller has answered the duplicate question. `update` sets `mode = "update"` and `target_patient_id`. `create_new` sets `duplicate_acknowledged = True`. Returns `{"status": "ok", "mode": "update"|"create"}`, or `{"status": "not_found"}` for `update` when no lookup matched.

### `commit_record(draft_id: str, caller_confirmed: bool)`
Rules:
- `caller_confirmed` must be `true`, else `{"status": "not_confirmed"}`.
- `draft_id` must be the latest draft, else `{"status": "stale_draft"}`.
- Validation re-runs server-side, then the write happens through `core.services`.

Successful results:
```json
{"status": "saved", "action": "create", "first_name": "Jane"}
{"status": "saved", "action": "update", "first_name": "Jane"}
```
- **Idempotent:** committing the same draft again returns the same result without writing twice. `patients.source_call_id` is unique, so the database also guarantees it.
- **On write failure:** retry once internally (250 ms backoff), then return `{"status": "system_error", "retryable": true}`. After the **second** failed tool call, return `{"status": "system_error", "retryable": false}` and mark the call `failed`. The payload is kept in `calls.final_payload`. If even that write fails, the payload is logged at ERROR level so staff can re-enter it.
- **On success:** set `calls.patient_id` and status `registered` or `updated`, and log the `registration.committed` event with the **final payload** (an assessment requirement).
- **`SIMULATE_DB_FAILURE=true`** makes the repository's write methods raise, which lets tests and demos prove the caller hears an apology, not silence.

### `start_over()`
Clears the draft, mode, target, duplicate flag and offered slots. It keeps `call_id`, `language` and `caller_number`. Returns `{"status": "cleared"}`.

### `find_appointment_slots(preferred_date?: "MM/DD/YYYY", time_of_day?: "morning" | "afternoon" | "any")`
Requires `committed_patient_id`, else `{"status": "not_registered"}`. Uses `available_slots()` over 14 days and returns at most 3 slots. It prefers Spanish-speaking doctors when `language == "Spanish"`.
```json
{"status": "ok", "slots": [{"slot_id": "s1", "doctor": "Dr. Priya Shah", "spoken": "Tuesday, September 29th at 10:30 AM"}]}
{"status": "none", "next_available": [ ...up to 3 from any day... ]}
```
`slot_id` values are opaque and scoped to the session. A `preferred_date` that isn't `MM/DD/YYYY` gives `{"status": "invalid", ...}`. The spoken times come from `core/speech.py` (`say_slot`), in the clinic's time zone and `state.language`.

### `book_appointment(slot_id: str)`
Inserts with `booked_via = 'voice_agent'` and `call_id`. The database exclusion constraint decides whether the slot is taken; the tool maps that violation to `{"status": "slot_taken", "alternatives": [...]}`. Success: `{"status": "booked", "spoken": "Tuesday, September 29th at 10:30 AM with Dr. Priya Shah"}`. Also `{"status": "not_registered"}` before a save, and `{"status": "unknown_slot"}` for an id that wasn't offered.

### `set_language(language: "English" | "Spanish")`
Switches the TTS voice and language, sets `state.language` (read-backs and spoken forms follow it) and updates `calls.language`. Returns `{"status": "ok", "language": "Spanish"}`. It does **not** change `preferred_language` by itself; the prompt asks the LLM to include that in the record.

### `end_call(reason: "completed" | "caller_request" | "no_response" | "emergency" | "out_of_scope")`
Hangs up once the current reply has been spoken, including the goodbye the LLM says in answer to this result: it shuts the session down from the speech handle's done callback, as LiveKit's `EndCallTool` does. So the prompt has the LLM call `end_call` first and say its last words after it; a goodbye can't be skipped or cut off. The session is started with `RoomOptions(delete_room_on_close=True)`, so closing it deletes the room, which hangs up a phone call (in console mode LiveKit skips the delete); the session's close also ends the job, which runs the shutdown handler. Returns `{"status": "ending"}`.

## 5. Call lifecycle and persistence

1. **Session start:** insert a `calls` row (`in_progress`, channel, caller number, room name), build the prompt, start the session, play the greeting.
2. **During the call:** tools update state and `calls.final_payload`.
3. **Shutdown handler** (runs on normal end, hang-up, or network drop):
   - Save the transcript from session history as `[{role, text, at}]`.
   - Set `ended_at` and `end_reason`.
   - Set the final status: `registered`/`updated` if committed; `failed` if a commit failed; `abandoned` if it ended before commit with collected data; otherwise `no_action`.
   - Generate a 2–3 sentence English **summary** via a one-off LLM call, only if the caller spoke at least 2 turns. It's best-effort, never blocks, and ignores failures.
   - Link `calls.patient_id` for both creates and updates.
4. A dropped call **never** creates or changes a patient. Only a confirmed commit writes, by design.

## 6. Scripts (fixed text)

- **Greeting (EN):** "Hi, thanks for calling {{clinic_name}}. This is {{agent_name}}, the clinic's virtual assistant. I can get you registered as a new patient in just a few minutes. To start, what's your first and last name?"
- **Silence (EN):** "Are you still there?" Then: "It sounds like we got disconnected. Feel free to call back anytime. Goodbye!"
- **Spanish equivalents** live in `agent/scripts.py`, not in the prompt.

## 7. Edge cases (each must have a test or a documented manual check; see `testing.md`)

| Scenario | Expected behavior | Enforced by |
|---|---|---|
| Future date of birth / 3-digit phone / bad ZIP | Explains briefly, re-asks **only** that field | Prompt + `prepare_record` errors |
| Spelled correction ("D-A-V-I-S, not D-A-V-I-E-S") | Updates only the last name, spells it back, continues | Prompt + new draft |
| Out-of-order answers | Keeps everything volunteered, asks only for what's missing | Prompt |
| Caller interrupts | Agent stops speaking and listens | LiveKit interruption handling |
| "Start over" | `start_over`, then "No problem, let's start fresh", then the name | Tool + prompt |
| Phone matches existing patient | The assessment's exact sentence; update path or create-new | `lookup` + `acknowledge_duplicate` |
| Caller says "no" to read-back | Fixes the item, calls `prepare_record` again, reads back **only** the change | Stale-draft guard |
| Database write fails | Apology, one retry offer, then "staff will call you back at …", graceful end | `commit_record` failure path |
| Call drops mid-registration | Nothing saved to `patients`; call marked `abandoned` with transcript and draft | Shutdown handler |
| "Hablo español" | `set_language(Spanish)`; everything continues in Spanish, including read-back and goodbye | Tool + prompt |
| Emergency described | "Please hang up and call 911 now," then `end_call(emergency)` | Prompt |
| Medical/billing question | "A clinician/the front desk can help with that," then continue registration | Prompt |
| "Am I talking to a real person?" | "I'm the clinic's virtual assistant." | Prompt |
| Silence | Two prompts, then a polite end | Session config |
| LLM provider failure | Fallback LLM continues the call seamlessly | Fallback adapter |
| Cartesia credits exhausted | Deepgram voice continues the call | Fallback adapter |

## 8. Observability events (structlog JSON to stdout; every line carries `call_id`)

| Event | Level | Fields |
|---|---|---|
| `call.started` | info | channel, caller_number (last 4 digits only), room |
| `tool.called` | info | tool, status, latency_ms |
| `registration.committed` | info | **full final payload**, action, patient_id |
| `registration.failed` | error | full payload, error class |
| `call.ended` | info | status, end_reason, duration_s, turns, language |
| `llm.fallback_used` / `tts.fallback_used` | warning | provider, error |
