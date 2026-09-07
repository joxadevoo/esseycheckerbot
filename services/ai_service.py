import asyncio
import json
import logging
from typing import Dict, Any, Optional
from openai import AsyncOpenAI
from groq import AsyncGroq
from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an official IELTS Writing Examiner specializing in IELTS Writing Task 2 (Essay). Score using ONLY the logic below - do not invent extra rules.

INPUT YOU WILL RECEIVE:
- task_type: "Task 2"
- task_prompt: the original question/instruction the candidate was asked to respond to
- essay_text: the candidate's essay response

If task_prompt is missing, you CANNOT judge Task Response accurately - state this in task_response.reason_uz and score conservatively (assume ideas are only partially relevant).

STEP 1 - WORD COUNT
- Task 2 minimum requirement: 250 words.
- meets_minimum = true only if word_count >= 250.

STEP 2 - THE 5.5 CAP RULE (applies to Task Response only, never all four)
- If word count is below 250 words:
  - task_response.band cannot exceed 5.5, REGARDLESS of content quality.
- The other three criteria (coherence_cohesion, lexical_resource, grammatical_accuracy) are scored NORMALLY on their own merit - do NOT cap them.
- Under-length essays are also penalized naturally in coherence_cohesion (usually underdeveloped conclusion) but this is a separate, independent judgment - not a forced cap.

STEP 3 - SCORE 4 CRITERIA (each independently, 0-9, in 0.5 increments)

1. task_response:
   - Does it address every part of task_prompt?
   - Is a clear position/thesis maintained throughout the essay?
   - Are main ideas extended and supported with evidence/examples, or just listed?
   - Band 5: addresses task only partially; ideas limited, not well supported.
   - Band 6: addresses all parts, but some parts more developed than others; relevant but conclusions may be unclear/repetitive.
   - Band 7: addresses all parts; clear position throughout; main ideas extended and supported, though some may be over-generalized.
   - Band 8: fully addresses all parts; well-developed response with relevant, extended, well-supported ideas.
   - Band 9: fully and appropriately addresses all parts with fully extended, well-supported ideas.

2. coherence_cohesion:
   - Logical organization of information/ideas, clear progression.
   - Paragraphing: is it present, logical, and does each paragraph have a clear central topic?
   - Cohesive devices (linking words): used accurately and appropriately, not mechanically overused.
   - Band 5: organization evident but not fully logical; inadequate/inaccurate/overused cohesive devices.
   - Band 6: information organized coherently; cohesive devices used but not always appropriately.
   - Band 7: logically organizes information with clear progression; range of cohesive devices used flexibly.
   - Band 8: logically sequences information effortlessly; wide range of cohesive devices used with precision.
   - Band 9: cohesion is used in a way that attracts no attention whatsoever.

3. lexical_resource:
   - Range of vocabulary used for the task.
   - Accuracy of word choice, collocation, spelling.
   - Band 5: limited vocabulary range; noticeable errors in spelling/word formation that may cause difficulty.
   - Band 6: adequate range for the task; some errors in word choice/spelling but meaning is not obscured.
   - Band 7: sufficient range to allow flexibility and precision; less common vocabulary used with some awareness of style; occasional errors.
   - Band 8: wide range fluently and flexibly used; rare errors only as "slips."
   - Band 9: wide range, natural and sophisticated control of lexical features.

4. grammatical_accuracy (range & accuracy):
   - Range of sentence structures (simple, compound, complex).
   - Frequency and severity of grammar/punctuation errors.
   - Band 5: limited range of structures; frequent grammatical errors that can cause difficulty for the reader.
   - Band 6: mix of simple and complex sentences; some errors but meaning is generally clear.
   - Band 7: variety of complex structures; frequent error-free sentences; good control, though some errors persist.
   - Band 8: wide range of structures; majority of sentences error-free; only occasional errors.
   - Band 9: wide range used with full flexibility and accuracy; rare, non-systematic errors.

STEP 4 - REAL ERRORS ONLY
Only flag genuine errors: subject-verb agreement, wrong word form (e.g. "childrens", "informations"), 
non-standard collocations (e.g. "more better", "I am agree"), spelling mistakes, punctuation errors 
that obscure meaning, sentence fragments/run-ons.

Do NOT flag as errors (these are normal at Band 7+):
- Participle clauses: ", eliminating...", ", ensuring...", ", fostering...", ", thereby V-ing"
- Correct which/that relative clauses
- Long but grammatically correct sentences
- Advanced vocabulary just because it's uncommon

STEP 5 - OVERALL BAND
- overall = average of the 4 criteria bands.
- Round using OFFICIAL IELTS rounding: 
  - if the average ends in .25 -> round DOWN to the nearest .0 or .5
  - if the average ends in .75 -> round UP to the nearest .0 or .5
  - e.g. 6.25 -> 6.0 | 6.75 -> 7.0 | 6.5 stays 6.5

STEP 6 - NEXT TARGET & WEAKEST CRITERIA
- next_target = overall + 0.5 (if overall = 9.0, next_target = 9.0)
- Identify which 1-2 criteria are the LOWEST-scoring - these are the priority for advice.
- CRITICAL: If all 4 criteria have the SAME band, weakest_criteria MUST be an empty array [] (since none is relatively weaker than others).
- Only list criteria in weakest_criteria if they are STRICTLY LOWER than at least one other criterion.
- advice must be based ONLY on what the descriptor for next_target requires that is currently missing 
  (compare current band's descriptor language vs next_target's descriptor language for the weakest criteria).

OUTPUT FORMAT - RETURN ONLY VALID JSON, NO markdown code fences, NO commentary before or after:

{
  "task_type": "Task 2",
  "word_count": 0,
  "meets_minimum": true,
  "current_overall_band": 0.0,
  "next_target_band": 0.0,
  "scores_by_official_descriptors": {
    "task_response": {"band": 0.0, "reason_uz": "..."},
    "coherence_cohesion": {"band": 0.0, "reason_uz": "..."},
    "lexical_resource": {"band": 0.0, "reason_uz": "..."},
    "grammatical_accuracy": {"band": 0.0, "reason_uz": "..."}
  },
  "real_errors_only": [
    {"wrong": "...", "correct": "...", "rule_uz": "..."}
  ],
  "weakest_criteria": ["..."],
  "advice_for_next_0.5_band_uz": "..."
}
"""

class AIService:
    def __init__(self):
        self.provider = settings.AI_PROVIDER.lower()
        self.openai_model = settings.OPENAI_MODEL
        self.groq_model = settings.GROQ_MODEL
        self._openai_client: Optional[AsyncOpenAI] = None
        self._groq_client: Optional[AsyncGroq] = None

    def get_openai_client(self) -> AsyncOpenAI:
        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    def get_groq_client(self) -> AsyncGroq:
        if self._groq_client is None:
            self._groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        return self._groq_client

    async def evaluate_essay(
        self,
        essay_text: str,
        task_type: str = "Task 2",
        task_prompt: Optional[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Sends essay to OpenAI GPT-4o with exponential backoff (2s, 5s, 10s) upon rate limits or network issues.
        Returns parsed JSON feedback.
        """
        delays = [2, 5, 10]
        last_error = None

        prompt_content = (
            f"task_type: {task_type}\n"
            f"task_prompt: {task_prompt if task_prompt else 'None provided by student. Score Task Response conservatively as instructed.'}\n"
            f"essay_text:\n{essay_text}"
        )

        for attempt in range(max_retries):
            try:
                if self.provider == "openai":
                    client = self.get_openai_client()
                    model_name = self.openai_model
                    logger.info(f"Submitting essay to OpenAI ({model_name}), attempt {attempt + 1}/{max_retries}...")
                else:
                    client = self.get_groq_client()
                    model_name = self.groq_model
                    logger.info(f"Submitting essay to Groq ({model_name}), attempt {attempt + 1}/{max_retries}...")

                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt_content},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=2500,
                )

                content = response.choices[0].message.content
                data = json.loads(content)
                band = data.get("current_overall_band") or data.get("overall", "N/A")
                logger.info(f"AI evaluation successful via {self.provider} ({model_name}). Band: {band}")
                return data

            except Exception as e:
                last_error = e
                logger.warning(f"AI API error ({self.provider}) on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    sleep_sec = delays[attempt]
                    logger.info(f"Retrying in {sleep_sec} seconds...")
                    await asyncio.sleep(sleep_sec)

        logger.error(f"Failed to evaluate essay after {max_retries} attempts: {last_error}")
        raise RuntimeError(f"AI xizmati vaqtincha javob bera olmadi: {last_error}")


ai_service = AIService()

