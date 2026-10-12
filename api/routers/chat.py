import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile

from api.deps import get_app_state
from models.schemas import ChatRequest, ChatResponse, ClarificationOption, RetrievedChunk, SourceCitation
from rag.diagnostic_graph import _parse_row_fields
from storage.feedback_store import FeedbackStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@dataclass
class DiagnosticTurnState:
    candidates: list[RetrievedChunk] = field(default_factory=list)
    original_query: str = ""


SESSION_STATE: dict[str, DiagnosticTurnState] = {}
PENDING_FEEDBACK: dict[str, dict[str, str]] = {}
REFINE_PENDING: dict[str, dict[str, str]] = {}
SESSION_FEEDBACK: dict[str, dict[str, str]] = {}

GREETINGS = {
    "hi",
    "hey",
    "hello",
    "hii",
    "hiya",
    "good morning",
    "good afternoon",
    "good evening",
}
GREETING_FILLER_WORDS = {"there", "assistant", "bot", "please"}


def _normalized_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9-]+", text.lower())


def _is_greeting(query: str) -> bool:
    words = _normalized_words(query)
    normalized = " ".join(words)
    if normalized in GREETINGS:
        return True
    return bool(words and words[0] in {"hi", "hey", "hello", "hii", "hiya"} and len(words) <= 3 and set(words[1:]) <= GREETING_FILLER_WORDS)


def _classify_query(query: str) -> str:
    """Classify a message before it can reach retrieval or the LLM."""
    if _is_greeting(query):
        return "greeting"
    if _is_out_of_scope(query):
        return "out_of_scope"
    return "maintenance"


def _has_specific_identifier(query: str) -> bool:
    return bool(re.search(r"\b[a-z]{1,8}[-_ ]?\d{2,}\b|#\d+", query, flags=re.IGNORECASE))


def _already_has_selected_context(query: str) -> bool:
    return "selected context:" in query.lower() or "use this as the search angle:" in query.lower()


def _selection_number(query: str) -> int | None:
    text = query.strip().lower()
    match = re.fullmatch(r"(?:option|incident|case|#)?\s*(\d{1,2})", text)
    if not match:
        return None
    return int(match.group(1))


def _needs_clarification(query: str) -> bool:
    if _already_has_selected_context(query) or _has_specific_identifier(query):
        return False

    words = _normalized_words(query)
    if len(words) < 2:
        return False

    manufacturing_terms = {
        "alarm",
        "axis",
        "breakdown",
        "current",
        "drive",
        "error",
        "fault",
        "failure",
        "jam",
        "leak",
        "motor",
        "overheat",
        "plc",
        "pressure",
        "robot",
        "sensor",
        "servo",
        "temperature",
        "vibration",
        "weld",
    }
    vague_terms = {"error", "fault", "issue", "problem", "failure", "stopped", "not", "working", "fix"}

    has_manufacturing_signal = any(word in manufacturing_terms for word in words)
    has_vague_signal = any(word in vague_terms for word in words)
    return has_manufacturing_signal and (len(words) <= 4 or has_vague_signal and len(words) <= 6)


# ---------------------------------------------------------------------------
# Out-of-scope / prompt-injection pre-flight check
# ---------------------------------------------------------------------------

# Topics that are clearly never equipment-maintenance queries.
_OOT_HARD_SIGNALS: frozenset[str] = frozenset({
    # weather
    "weather", "forecast", "rain", "sunny", "humidity", "wind", "snow",
    "climate", "celsius", "fahrenheit",
    # general knowledge / trivia
    "recipe", "cooking", "bake", "movie", "film", "music", "song", "lyrics",
    "sport", "football", "cricket", "soccer", "basketball", "baseball",
    "news", "politics", "election", "president", "government",
    "stock", "market", "crypto", "bitcoin", "finance", "investment",
    "joke", "poem", "story", "write", "essay",
    # coding / general tech help (not manufacturing)
    "python", "javascript", "java", "typescript", "html", "css",
    "github", "git", "docker", "kubernetes", "linux", "ubuntu",
    # prompt injection signals
    "ignore", "disregard", "forget", "system prompt", "instructions",
    "jailbreak", "dan", "pretend you", "act as", "roleplay",
    "reveal", "expose", "show me your", "what are your instructions",
})

# At least one of these must appear for a query to be considered in-scope.
_IN_SCOPE_SIGNALS: frozenset[str] = frozenset({
    "alarm", "axis", "bearing", "belt", "brake", "breakdown", "calibrat",
    "circuit", "clamp", "component", "controller", "conveyor", "coolant",
    "current", "cycle", "diagnos", "drive", "encoder", "equipment",
    "error", "failure", "fault", "fixture", "gear", "hmi", "hydraulic",
    "incident", "interlock", "jam", "leak", "limit", "lubrication",
    "machine", "maintenance", "manual", "motor", "noise", "overload",
    "overheat", "plc", "pneumatic", "pressure", "pump", "repair",
    "robot", "scrap", "sensor", "servo", "signal", "spindle",
    "station", "stopped", "temperature", "torque", "transformer",
    "trip", "valve", "vibration", "voltage", "weld", "worn",
})


def _is_out_of_scope(query: str) -> bool:
    """Return True when the query is clearly unrelated to equipment maintenance.

    Two-pass approach:
    1. Hard-block — any known off-topic signal word immediately rejects.
    2. No-signal — if the query contains zero manufacturing vocabulary it is
       treated as out of scope (catches generic conversational questions like
       "What is the weather today?").

    Deliberately conservative: an ambiguous query passes through and the
    agent / LLM can still decide it's irrelevant.
    """
    text_lower = query.lower()
    words = set(_normalized_words(query))

    # Pass 1 — hard block on explicit off-topic or injection signals.
    for signal in _OOT_HARD_SIGNALS:
        if signal in text_lower:
            logger.info("Out-of-scope hard-block matched: %r (query: %r)", signal, query[:80])
            return True

    # Pass 2 — require at least one manufacturing term (prefix match for
    # words like "calibrate"/"calibration", "diagnose"/"diagnostic").
    has_in_scope = any(
        any(word.startswith(sig) for word in words)
        for sig in _IN_SCOPE_SIGNALS
    )
    if not has_in_scope:
        logger.info("Out-of-scope: no manufacturing vocabulary detected (query: %r)", query[:80])
        return True

    return False


_OUT_OF_SCOPE_REPLY = (
    "I can only answer questions based on the equipment maintenance documents "
    "in this knowledge base. Please describe a machine fault, alarm code, or "
    "maintenance issue and I\'ll search the knowledge base for you."
)

CONFIRMED_FIX_PROMPT = """You are producing the final, actionable answer for a maintenance engineer who is standing at the machine right now. They already confirmed which incident record matches what they're seeing — your job is to turn that record into something they can execute from without reading it twice.

Respond in EXACTLY this structure, every section required:

**Issue:** <one plain-language sentence — what the engineer is observing, not the incident ID>
**Likely cause:** <one sentence, from the record's root cause field>

**Fix:**
1. <concrete step>
2. <concrete step>
(as many numbered steps as the record supports — do not pad or invent steps not grounded in the record)

**Verify:** <one concrete, observable check that confirms the fix actually worked — not "monitor the system">
**Safety:** <lockout/tagout, PPE, or power-down note; write "None beyond standard LOTO" if the record has nothing specific>

_Source: <incident-id> · <source file>_

Rules:
- Every step must be something a person can physically do on the shop floor — no vague steps like "investigate the issue" or "check the wiring" without saying what to check it for or against.
- Do not mention other candidate incidents.
- If the record is missing a field (no listed safety note, no explicit verification step), write "Not recorded" rather than omitting the line or inventing one.
- Never lead the Issue line with the incident ID or code."""

DISAMBIGUATION_LINE_PROMPT = """For the incident record below, write ONE sentence describing the observable fault the way an engineer would say it out loud on the floor — equipment/station first, then the symptom. No incident ID inside the sentence. If the record has no explicit symptom text, describe the fault from whatever fields exist (equipment, subsystem, error code) rather than returning nothing.

Record:
{incident_fields}

Return only the sentence, no leading number, no trailing period-less fragment."""


def _clarification_options_for(query: str) -> list[ClarificationOption]:
    q = query.lower()

    if "weld" in q:
        options = [
            ("weld-alarm", "Weld alarm or code", "Focus on the displayed weld fault, alarm number, current error, or voltage error.", "weld alarm code current voltage error"),
            ("weld-quality", "Weld quality issue", "Focus on spatter, weak welds, burn-through, missing nugget, or failed quality checks.", "weld quality spatter weak weld burn through nugget"),
            ("weld-hardware", "Gun, tip, or cap", "Focus on weld gun, electrode tip/cap wear, transformer, cable, shunt, or water-cooling hardware.", "weld gun electrode tip cap transformer cable shunt cooling"),
            ("robot-station", "Robot or station", "Focus on robot motion, station interlock, fixture, clamp, part presence, or program step.", "robot station interlock fixture clamp part presence program"),
        ]
    elif any(term in q for term in ("servo", "axis", "drive", "motor")):
        options = [
            ("drive-alarm", "Drive alarm or code", "Focus on the servo drive, axis amplifier, displayed alarm, or fault number.", "servo drive axis amplifier alarm code"),
            ("motion-symptom", "Motion behavior", "Focus on whether the axis will not move, drifts, hunts, vibrates, or stops mid-cycle.", "axis motion will not move drift hunting vibration stopped"),
            ("load-mechanical", "Load or mechanical bind", "Focus on overload, brake, coupling, belt, bearing, lubrication, or mechanical binding.", "overload brake coupling belt bearing lubrication mechanical bind"),
            ("feedback-home", "Encoder or home", "Focus on encoder feedback, home position, limit switch, following error, or position loss.", "encoder home limit switch following error position loss"),
        ]
    elif any(term in q for term in ("sensor", "plc", "interlock", "signal", "io", "i/o")):
        options = [
            ("sensor-state", "Sensor state", "Focus on the sensor type, expected state, actual state, and what changed in the cycle.", "sensor expected actual state cycle"),
            ("plc-io", "PLC or I/O", "Focus on PLC input/output, network module, safety circuit, or missing signal.", "plc input output io network safety missing signal"),
            ("part-fixture", "Part or fixture", "Focus on part presence, fixture clamp, locator, nest, or misalignment.", "part presence fixture clamp locator nest misalignment"),
            ("maintenance-action", "Recent change", "Focus on a recent replacement, cleaning, adjustment, upload, or maintenance action.", "recent replacement cleaning adjustment upload maintenance"),
        ]
    else:
        options = [
            ("alarm-code", "Alarm or error code", "Focus on the exact alarm number, message, HMI text, or controller fault.", "alarm code error hmi controller fault"),
            ("machine-symptom", "Machine symptom", "Focus on what the machine did, when it happened, and whether it repeats.", "machine symptom timing repeat cycle behavior"),
            ("equipment-area", "Equipment area", "Focus on the line, station, robot, machine model, subsystem, or component involved.", "line station robot machine model subsystem component"),
            ("recent-work", "Recent maintenance", "Focus on parts changed, resets, PM work, adjustments, or unusual events before the fault.", "recent maintenance parts changed reset adjustment unusual event"),
        ]

    return [
        ClarificationOption(id=id_, label=label, context=context, search_hint=search_hint)
        for id_, label, context, search_hint in options
    ]


def _clarification_response(query: str, reason: str = "missing-context") -> ChatResponse:
    if reason == "low-confidence":
        answer = "Need one more clue — which angle should I use?"
    else:
        answer = "One more detail — which angle matches this issue?"

    return ChatResponse(
        answer=answer,
        sources=[],
        confidence=0.0,
        agent_steps=[],
        suggestions=_clarification_options_for(query),
    )


def _incident_field(chunk: RetrievedChunk, *names: str) -> str:
    fields = _parse_row_fields(chunk.chunk.text)
    normalized = {key.strip().lower().replace(" ", "_"): value for key, value in fields.items()}
    for name in names:
        for candidate in (name, name.replace("_", " ")):
            value = normalized.get(candidate)
            if value:
                return value
    for name in names:
        # fallback for raw text fragments outside row format
        if name in chunk.chunk.text.lower():
            match = re.search(rf"(?i){re.escape(name.replace('_', ' '))}[:\- ]+(.+?)(?=\||$)", chunk.chunk.text)
            if match:
                return match.group(1).strip()
    return ""


def _sentence_case(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "")).strip().rstrip(". ;")
    if not text:
        return ""
    text = text.replace("|", ",")
    if not text.endswith((".", "!", "?")):
        text += "."
    return text[0].upper() + text[1:]


def _equipment_anchor(chunk: RetrievedChunk) -> str:
    fields = _parse_row_fields(chunk.chunk.text)
    for key, value in fields.items():
        lowered = key.lower()
        if any(term in lowered for term in ("station", "cell", "robot", "equipment", "machine", "line", "area")):
            if value.strip():
                return value.strip()
    text = chunk.chunk.text
    match = re.search(r"\b(?:station|cell|robot|machine|line|equipment)\s*[:#-]?\s*(\d+[A-Za-z0-9-]*)", text, flags=re.IGNORECASE)
    if match:
        raw = match.group(0).strip()
        if re.match(r"(?i)^(station|cell|robot|machine|line|equipment)\b", raw):
            return raw.title()
        prefix = re.match(r"(?i)(station|cell|robot|machine|line|equipment)", raw)
        if prefix:
            return f"{prefix.group(1).title()} {match.group(1)}".strip()
    match = re.search(r"\b(?:station|cell|robot|machine|line|equipment)\s+([A-Za-z0-9-]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(0).strip().title()
    return "Equipment"


def _candidate_sentence(chunk: RetrievedChunk) -> str:
    fields = _parse_row_fields(chunk.chunk.text)
    incident_id = _incident_id(chunk)
    symptom = (
        _incident_field(chunk, "symptom", "fault_description", "description", "issue", "problem", "error_desc")
        or _incident_field(chunk, "error_code", "fault_code", "code")
        or ""
    )
    if not symptom:
        for key, value in fields.items():
            lowered = key.lower()
            if any(term in lowered for term in ("symptom", "fault", "description", "issue", "error")):
                symptom = value
                break
    if not symptom:
        equipment = _equipment_anchor(chunk)
        component = _incident_field(chunk, "subsystem", "component", "equipment_part", "part", "assembly")
        error_code = _incident_field(chunk, "error_code", "fault_code", "code")
        bits = [part for part in [equipment, component, error_code] if part]
        if bits:
            return _sentence_case(f"{bits[0]} — {' '.join(bits[1:])} fault logged on the equipment.")
        return _sentence_case(f"Equipment fault logged in the record without a more specific symptom. ({incident_id})")

    equipment = _equipment_anchor(chunk)
    sentence = f"{equipment} — {_sentence_case(symptom).rstrip('.')}"
    return sentence


def _incident_id(chunk: RetrievedChunk) -> str:
    text = chunk.chunk.text or ""
    direct = _incident_field(chunk, "incident_id", "id", "case_id")
    if direct:
        return direct

    match = re.search(r"\b(?:incident|case|issue)\s*(?:id)?\s*[:#-]?\s*([A-Z0-9-]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()

    match = re.search(r"\b([A-Z]{1,8}-\d{2,})\b", text)
    if match:
        return match.group(1)

    return f"source row {chunk.chunk.chunk_index + 1}"


def _candidate_label(chunk: RetrievedChunk) -> str:
    incident = _incident_id(chunk)
    component = _incident_field(chunk, "subsystem", "component", "equipment")
    symptom = _incident_field(chunk, "symptom", "fault_description", "description", "issue")
    if component and symptom:
        return f"{incident}: {component} - {symptom[:90]}"
    if symptom:
        return f"{incident}: {symptom[:110]}"
    return f"{incident}: {chunk.chunk.text[:110]}"


def _short_text(value: str | None, max_chars: int = 100) -> str:
    if not value:
        return ""
    text = value.strip().rstrip(".")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars-3].rstrip()}..."


def _compact_incident_summary(chunk: RetrievedChunk) -> str:
    incident = _incident_id(chunk)
    component = _incident_field(chunk, "subsystem", "component", "equipment")
    if not component:
        station_match = re.search(r"\b(?:station|cell|line|robot)\s*[:#-]?\s*(\d+[A-Za-z0-9-]*)", chunk.chunk.text, flags=re.IGNORECASE)
        if station_match:
            component = f"Station {station_match.group(1)}"
    symptom = _short_text(_incident_field(chunk, "symptom", "fault_description", "description", "issue"), 90)
    root_cause = _short_text(_incident_field(chunk, "root_cause", "rootcause", "cause"), 80)
    action = _short_text(_incident_field(chunk, "solution", "resolution", "corrective_action", "fix", "remedy"), 80)

    if component and symptom:
        lead = f"{incident} — {component}: {symptom}"
    elif symptom:
        lead = f"{incident} — {symptom}"
    elif component:
        lead = f"{incident} — {component}"
    else:
        lead = incident

    if root_cause:
        lead = f"{lead}; likely {root_cause}"
    if action:
        lead = f"{lead}; action: {action}"
    return lead.strip("; ")


def _source_for(chunk: RetrievedChunk) -> SourceCitation:
    snippet = chunk.chunk.text[:200] + ("..." if len(chunk.chunk.text) > 200 else "")
    return SourceCitation(
        tenant_id=chunk.chunk.tenant_id,
        file=chunk.chunk.source_file,
        page=chunk.chunk.page_number,
        snippet=snippet,
        chunk_index=chunk.chunk.chunk_index,
    )


def _candidate_options(candidates: list[RetrievedChunk]) -> list[ClarificationOption]:
    options = []
    for idx, candidate in enumerate(candidates[:5], start=1):
        options.append(
            ClarificationOption(
                id=f"candidate-{idx}",
                label=str(idx),
                context=f"Use candidate {idx}: {_candidate_label(candidate)}",
                search_hint=_incident_id(candidate),
            )
        )
    return options


def _feedback_options() -> list[ClarificationOption]:
    return [
        ClarificationOption(
            id="feedback-yes",
            label="Yes",
            context="Confirm the fix resolved the issue",
            search_hint="yes",
        ),
        ClarificationOption(
            id="feedback-partially",
            label="Partially",
            context="The fix partially resolved the issue",
            search_hint="partially",
        ),
        ClarificationOption(
            id="feedback-no",
            label="No",
            context="The fix did not resolve the issue",
            search_hint="no",
        ),
    ]


def _store_candidates(session_id: str | None, query: str, candidates: list[RetrievedChunk]) -> None:
    if session_id and candidates:
        SESSION_STATE[session_id] = DiagnosticTurnState(candidates=candidates[:5], original_query=query)


def _feedback_store(state) -> FeedbackStore | None:
    store = getattr(state, "feedback_store", None)
    return store if isinstance(store, FeedbackStore) else None


def _save_pending_feedback(state, session_id: str | None, selected: RetrievedChunk, query: str, state_name: str = "awaiting_outcome") -> None:
    if not session_id:
        return
    payload = {
        "tenant_id": selected.chunk.tenant_id,
        "chunk_id": selected.chunk.id,
        "incident_id": _incident_id(selected),
        "source_file": selected.chunk.source_file,
        "query": query,
        "state": state_name,
    }
    PENDING_FEEDBACK[session_id] = payload
    store = _feedback_store(state)
    if store:
        store.save_pending(
            session_id=session_id,
            tenant_id=payload["tenant_id"],
            query_text=query,
            chunk_id=payload["chunk_id"],
            incident_id=payload["incident_id"],
            source_file=payload["source_file"],
            state=state_name,
        )


def _load_pending_feedback(state, session_id: str | None) -> dict[str, str] | None:
    if not session_id:
        return None
    pending = PENDING_FEEDBACK.get(session_id)
    if pending:
        return pending
    store = _feedback_store(state)
    pending = store.get_pending(session_id) if store else None
    if pending:
        PENDING_FEEDBACK[session_id] = pending
    return pending


async def _answer_selected_candidate(
   selected: RetrievedChunk,
   user_query: str,
   state,
   session_id: str | None = None,
) -> ChatResponse:
   incident = _incident_id(selected)
   source_file = selected.chunk.source_file
   root_cause = _incident_field(selected, "root_cause", "rootcause", "cause") or "Not recorded"
   solution = _incident_field(selected, "solution", "resolution", "corrective_action", "fix", "remedy")
   symptom = _incident_field(selected, "symptom", "fault_description", "description", "issue", "problem") or "Not recorded"
   verify = _incident_field(selected, "verify", "verification", "check", "validation") or "Not recorded"
   safety = _incident_field(selected, "safety", "lockout", "ppe", "safeguard") or "None beyond standard LOTO"

   prompt, sources = state.context_builder.build(
       f"""The user selected candidate incident {incident} after asking: {user_query}

The record to answer from is:
{selected.chunk.text}

Use the exact output structure required by the maintenance engineer. Do not mention other incidents. If the record is missing a field, write "Not recorded" instead of omitting it.""",
       [selected],
   )

   prompt = f"{CONFIRMED_FIX_PROMPT}\n\nRecord:\n{selected.chunk.text}\n\nIncident ID: {incident}\nSource file: {source_file}"

   response_text = (
       "**Issue:** " + _sentence_case(symptom) + "\n"
       "**Likely cause:** " + _sentence_case(root_cause) + "\n\n"
       "**Fix:**\n"
       "1. Power down the cell and apply lockout/tagout before opening the cabinet or touching the tool.\n"
       "2. Inspect the recorded failure area and compare it with the selected source record for wear, drift, contamination, or misalignment.\n"
       "3. Correct the identified fault and re-run the machine in a controlled test cycle.\n\n"
       "**Verify:** " + _sentence_case(verify) + "\n"
       "**Safety:** " + _sentence_case(safety) + "\n\n"
       f"_Source: {incident} · {source_file}_\n\n"
       "Did that resolve it? (yes / partially / no)"
   )

   try:
       answer = await state.ollama.generate(prompt, stream=False)
       if isinstance(answer, str) and answer.strip():
           response_text = answer.strip() + "\n\nDid that resolve it? (yes / partially / no)"
   except Exception:
       logger.exception("LLM generation failed while answering selected candidate")

   feedback_suggestions = []
   if session_id:
       SESSION_FEEDBACK[session_id] = {"incident_id": incident, "source_file": source_file, "query": user_query}
       _save_pending_feedback(state, session_id, selected, user_query)
       feedback_suggestions = _feedback_options()

   return ChatResponse(
       answer=response_text,
       sources=sources or [_source_for(selected)],
       confidence=round(1 / (1 + pow(2.718, -selected.rerank_score)), 3),
       agent_steps=[],
       suggestions=feedback_suggestions,
   )


def _feedback_reply(query: str) -> str | None:
   text = query.strip().lower()
   if text in {"yes", "y"}:
       return "yes"
   if text in {"no", "n"}:
       return "no"
   if text in {"partially", "partial", "partly"}:
       return "partially"
   return None


def _record_feedback_outcome(incident_id: str, query_text: str, outcome: str) -> None:
   db_path = Path("./data/feedback.sqlite3")
   db_path.parent.mkdir(parents=True, exist_ok=True)
   conn = sqlite3.connect(db_path)
   try:
       conn.execute(
           """
           CREATE TABLE IF NOT EXISTS feedback_outcomes (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               incident_id TEXT NOT NULL,
               outcome TEXT NOT NULL,
               query_text TEXT NOT NULL,
               created_at TEXT NOT NULL
           )
           """
       )
       conn.execute(
           "INSERT INTO feedback_outcomes (incident_id, outcome, query_text, created_at) VALUES (?, ?, ?, ?)",
           (incident_id, outcome, query_text, datetime.now(timezone.utc).isoformat()),
       )
       conn.commit()
   finally:
       conn.close()


def _update_graph_feedback_weight(state, incident_id: str, delta: int) -> None:
   graph = state.graph_store.load(state.settings.default_tenant_id)
   if graph is None:
       return
   if not isinstance(graph.graph.graph, dict):
       graph.graph.graph = {}
   graph.graph.graph.setdefault("feedback_weights", {})
   previous = graph.graph.graph["feedback_weights"].get(incident_id, 0)
   graph.graph.graph["feedback_weights"][incident_id] = max(0, previous + delta)
   state.graph_store.save(graph)


async def _handle_feedback(feedback: str, pending: dict[str, str], state, session_id: str | None) -> ChatResponse:
   incident_id = pending.get("incident_id", "unknown")
   query_text = pending.get("query", "")
   chunk_id = pending.get("chunk_id", "")
   tenant_id = pending.get("tenant_id", state.settings.default_tenant_id)
   source_file = pending.get("source_file", "")
   store = _feedback_store(state)

   if store and chunk_id:
       store.record_event(
           tenant_id=tenant_id,
           session_id=session_id,
           query_text=query_text,
           outcome={"yes": "confirmed", "no": "rejected", "partially": "partial"}[feedback],
           chunk_id=chunk_id,
           incident_id=incident_id,
           source_file=source_file,
       )
   if feedback == "yes":
       _record_feedback_outcome(incident_id, query_text, "confirmed")
       _update_graph_feedback_weight(state, incident_id, 1)
       PENDING_FEEDBACK.pop(session_id or "", None)
       if store and session_id:
           store.delete_pending(session_id)
       return ChatResponse(
           answer="Thanks — marked as confirmed.",
           sources=[],
           confidence=1.0,
           agent_steps=[],
       )

   if feedback == "no":
       _record_feedback_outcome(incident_id, query_text, "rejected")
       _update_graph_feedback_weight(state, incident_id, -1)
       PENDING_FEEDBACK.pop(session_id or "", None)
       if store and session_id:
           store.delete_pending(session_id)
       retrieved, agent_steps, graph_matches = await state.agent.run(query_text)
       filtered = [candidate for candidate in retrieved if _incident_id(candidate) != incident_id]
       if not filtered:
           return ChatResponse(
               answer="Ruling that one out — the knowledge base does not have another close match for this case yet.",
               sources=[],
               confidence=0.0,
               agent_steps=agent_steps,
           )
       _store_candidates(session_id, query_text, filtered[:5])
       answer = "Ruling that one out — here\'s what else is close:\n\n" + "\n".join(
           f"{idx}. {_candidate_sentence(candidate)} ({_incident_id(candidate)})"
           for idx, candidate in enumerate(filtered[:5], start=1)
       )
       return ChatResponse(
           answer=answer,
           sources=[_source_for(candidate) for candidate in filtered[:5]],
           confidence=0.8,
           agent_steps=agent_steps,
           suggestions=_candidate_options(filtered),
       )

   if feedback == "partially":
       pending["state"] = "awaiting_detail"
       REFINE_PENDING[session_id or ""] = pending
       if store and session_id:
           store.save_pending(
               session_id=session_id,
               tenant_id=tenant_id,
               query_text=query_text,
               chunk_id=chunk_id,
               incident_id=incident_id,
               source_file=source_file,
               state="awaiting_detail",
           )
       return ChatResponse(
           answer="What\'s still happening?",
           sources=[],
           confidence=0.6,
           agent_steps=[],
       )

   return ChatResponse(
       answer="I need a yes, no, or partially answer.",
       sources=[],
       confidence=0.0,
       agent_steps=[],
   )


async def _read_chat_request(http_request: Request) -> tuple[ChatRequest, UploadFile | None]:
    """Accept the legacy JSON contract as well as a query plus image multipart form."""
    content_type = http_request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await http_request.form()
        image = form.get("image")
        return ChatRequest(
            query=str(form.get("query") or ""),
            session_id=str(form.get("session_id") or "") or None,
        ), image if isinstance(image, UploadFile) else None

    try:
        return ChatRequest.model_validate(await http_request.json()), None
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Expected a chat JSON payload or multipart form") from exc


@router.post("", response_model=ChatResponse)
async def chat(http_request: Request) -> ChatResponse:
    request, image = await _read_chat_request(http_request)
    state = get_app_state()
    query = request.query.strip()
    if not query and image is None:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if image is not None:
        if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(status_code=415, detail="Attach a PNG, JPEG, or WebP image")
        image_bytes = await image.read(state.settings.chat_image_max_bytes + 1)
        if not image_bytes:
            raise HTTPException(status_code=400, detail="The attached image is empty")
        if len(image_bytes) > state.settings.chat_image_max_bytes:
            raise HTTPException(status_code=413, detail="Image must be 8 MB or smaller")
        try:
            observation = await state.ollama.describe_image(image_bytes, image.content_type, query)
        except Exception as exc:
            logger.exception("Image analysis failed")
            raise HTTPException(status_code=503, detail=f"Image analysis failed: {exc}") from exc
        query = query or "Analyze the attached equipment image."
        if observation:
            query = f"{query}\n\nImage observations: {observation}"

    feedback = _feedback_reply(query)
    pending = _load_pending_feedback(state, request.session_id)
    if feedback is not None and pending:
        return await _handle_feedback(feedback, pending, state, request.session_id)

    refine = REFINE_PENDING.get(request.session_id or "")
    if not refine and pending and pending.get("state") == "awaiting_detail":
        refine = pending
    if refine and feedback is None:
        original = refine.get("query", "")
        combined = f"{original} — still happening: {query}"
        REFINE_PENDING.pop(request.session_id or "", None)
        PENDING_FEEDBACK.pop(request.session_id or "", None)
        store = _feedback_store(state)
        if store and request.session_id:
            store.delete_pending(request.session_id)
        retrieved, agent_steps, graph_matches = await state.agent.run(combined)
        if retrieved:
            confidence = state.context_builder.compute_confidence(retrieved)
            prompt, sources = state.context_builder.build(combined, retrieved, graph_matches)
            try:
                answer = await state.ollama.generate(prompt, stream=False)
                response_text = answer.strip() if isinstance(answer, str) else ""
            except Exception:
                logger.exception("LLM generation failed while refining feedback")
                response_text = ""

            if not response_text:
                response_text = "A closer match was found, but the assistant could not summarize it safely."

            _store_candidates(request.session_id, combined, retrieved)
            _save_pending_feedback(state, request.session_id, retrieved[0], combined)
            response_text += "\n\nWas this diagnosis useful? (yes / partially / no)"
            return ChatResponse(
                answer=response_text,
                sources=sources,
                confidence=confidence,
                agent_steps=agent_steps,
                graph_matches=graph_matches,
                suggestions=_feedback_options() if request.session_id else [],
            )

        return ChatResponse(
            answer="No matching incident was found after adding that symptom.",
            sources=[],
            confidence=0.0,
            agent_steps=agent_steps,
        )

    selected_number = _selection_number(query)
    turn_state = SESSION_STATE.get(request.session_id or "")

    if selected_number is not None and turn_state:
        index = selected_number - 1
        if 0 <= index < len(turn_state.candidates):
            selected = turn_state.candidates[index]
            SESSION_STATE.pop(request.session_id or "", None)
            return await _answer_selected_candidate(selected, turn_state.original_query, state, request.session_id)
        return ChatResponse(
            answer=f"I only have {len(turn_state.candidates)} candidate incidents in the current set. Pick one of those numbers, or describe the issue another way.",
            sources=[_source_for(candidate) for candidate in turn_state.candidates],
            confidence=0.0,
            agent_steps=[],
            suggestions=_candidate_options(turn_state.candidates),
        )

    query_kind = _classify_query(query)

    if query_kind == "greeting":
        return ChatResponse(
            answer="Hi. Tell me the machine, error code, symptom, or station that is giving trouble and I will search the knowledge base.",
            sources=[],
            confidence=1.0,
            agent_steps=[],
        )

    # Fast pre-flight check: if the query is clearly out of scope (weather,
    # general knowledge, prompt injection, etc.) return immediately without
    # touching the RAG pipeline at all. This also prevents the loading skeleton
    # from persisting through a full agent loop for irrelevant queries.
    if query_kind == "out_of_scope":
        return ChatResponse(
            answer=_OUT_OF_SCOPE_REPLY,
            sources=[],
            confidence=0.0,
            agent_steps=[],
        )

    if _needs_clarification(query):
        return _clarification_response(query)

    # The agent decides how many searches to run and how to reformulate the
    # query — this replaces the old fixed "always exactly one retrieval
    # pass" behavior with something that can actually notice a bad first
    # search and try again.
    retrieved, agent_steps, graph_matches = await state.agent.run(query)

    # The agent returns all-empty when it deliberately flags the query as out of
    # scope or a prompt-injection attempt. Return a polite, fixed message without
    # exposing any internal details, system prompts, or knowledge-base contents.
    if not retrieved and not agent_steps and not graph_matches:
        return ChatResponse(
            answer=(
                "I can only answer questions based on the documents in this knowledge base. "
                "Please describe an equipment issue or maintenance problem and I'll do my best to help."
            ),
            sources=[],
            confidence=0.0,
            agent_steps=[],
        )

    confidence = state.context_builder.compute_confidence(retrieved)

    if confidence < state.settings.confidence_threshold:
        answer = "No direct match found."
        # If retrieval found *something*, even below the confidence bar, name
        # it instead of refusing blind — this is the difference between "I
        # searched and found nothing like this" and "I found some loosely
        # related records, none confident enough to answer from directly."
        if retrieved:
            candidates = retrieved[:3]
            lines = []
            for c in candidates:
                incident = _incident_id(c)
                component = _incident_field(c, "subsystem", "component", "equipment")
                symptom = _incident_field(c, "symptom", "fault_description", "description", "issue")
                # Build a single-sentence summary an engineer can scan at a glance.
                if component and symptom:
                    summary = f"{component} — {symptom[:80]}{'...' if len(symptom) > 80 else ''}"
                elif symptom:
                    summary = symptom[:100] + ("..." if len(symptom) > 100 else "")
                elif component:
                    summary = component
                else:
                    # Last resort: trim the raw text to first sentence or 80 chars.
                    raw = c.chunk.text.split(".")[0].strip()
                    summary = raw[:80] + ("..." if len(raw) > 80 else "")
                lines.append(f"- **{incident}**: {summary}")
            answer += " Closest historical lead: " + lines[0].removeprefix("- ") + "."
        else:
            answer += " Add the equipment name, alarm code, or observable symptom."

        return ChatResponse(
            answer=answer,
            sources=[],
            confidence=confidence,
            agent_steps=agent_steps,
            suggestions=_clarification_options_for(query),
        )

    prompt, sources = state.context_builder.build(query, retrieved, graph_matches)

    try:
        answer = await state.ollama.generate(prompt, stream=False)
        if isinstance(answer, str):
            response_text = answer.strip()
        else:
            response_text = ""
            async for token in answer:
                response_text += token
            response_text = response_text.strip()
    except Exception as e:
        logger.exception("LLM generation failed")
        raise HTTPException(status_code=503, detail=f"LLM generation failed: {e}") from e

    _store_candidates(request.session_id, query, retrieved)
    if retrieved:
        _save_pending_feedback(state, request.session_id, retrieved[0], query)
        response_text += "\n\nWas this diagnosis useful? (yes / partially / no)"
    return ChatResponse(
        answer=response_text,
        sources=sources,
        confidence=confidence,
        agent_steps=agent_steps,
        graph_matches=graph_matches,
        suggestions=_feedback_options() if retrieved and request.session_id else [],
    )
