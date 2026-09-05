from datetime import datetime
from typing import Any

from app.core.errors import ToolError
from app.core.i18n import detect_script, resolve_language
from app.domain.countries import COUNTRY_POLICIES
from app.integrations.ports import HRISPort
from app.knowledge.gaps import GapLog
from app.knowledge.store import COUNTRY_SPECIFIC_TOPICS, KnowledgeStore

# Below this score, a match is noise, not signal -- see docs/ROADMAP.md
# for how this was calibrated and its honest precision limit on a
# corpus this small.
_MATCH_THRESHOLD = 2.0


async def answer_hr_question(
    question: str,
    employee_id: str,
    *,
    hris: HRISPort,
    knowledge_store: KnowledgeStore,
    gap_log: GapLog,
    now: datetime,
) -> dict[str, Any]:
    # employee_id is required, not optional: this is what makes "never
    # guess the country" true by construction rather than by convention
    # -- there is no code path here that reaches a country-specific
    # answer without a resolved employee record behind it.
    employee = await hris.get_employee(employee_id)
    if employee is None:
        return ToolError(
            code="EMPLOYEE_NOT_FOUND",
            message_en="I couldn't find an employee record for that id.",
            message_ar="لم أتمكن من العثور على سجل موظف بهذا المعرف.",
            recovery_hint="Confirm the employee id came from resolve_employee, not user input.",
        ).to_response()

    language = resolve_language(employee.preferred_language, detect_script(question))
    results = knowledge_store.search(question, language, top_k=1)

    if not results or results[0].score < _MATCH_THRESHOLD:
        gap_log.record(question, employee_id, employee.country, now)
        return ToolError(
            code="NO_SOP_FOUND",
            message_en=(
                "I don't have a documented answer for that. I've logged it so HR can add "
                "guidance."
            ),
            message_ar=(
                "ليس لدي إجابة موثقة لهذا السؤال. تم تسجيله حتى تضيف الموارد البشرية توجيهًا."
            ),
            recovery_hint="Logged as a knowledge gap and escalated to HR; no answer to give yet.",
        ).to_response()

    chunk = results[0].chunk
    if chunk.topic in COUNTRY_SPECIFIC_TOPICS and employee.country not in COUNTRY_POLICIES:
        gap_log.record(question, employee_id, employee.country, now)
        return ToolError(
            code="COUNTRY_NOT_SUPPORTED",
            message_en=f"This answer depends on country-specific policy, and '{employee.country}' "
            "isn't configured yet.",
            message_ar=f"تعتمد هذه الإجابة على سياسة خاصة بالدولة، ولم يتم إعداد "
            f"'{employee.country}' بعد.",
            recovery_hint="Escalate to HR -- this employee's country has no policy encoded.",
            data={"country": employee.country},
        ).to_response()

    other_language = "ar" if language == "en" else "en"
    other_chunk = knowledge_store.get_chunk(chunk.topic, chunk.section_index, other_language)
    english_text = chunk.text if language == "en" else (other_chunk.text if other_chunk else "")
    arabic_text = chunk.text if language == "ar" else (other_chunk.text if other_chunk else "")

    return {
        "ok": True,
        "data": {
            "source_doc": chunk.topic,
            "section": chunk.section,
            "language": language,
        },
        "message_en": english_text,
        "message_ar": arabic_text,
    }
