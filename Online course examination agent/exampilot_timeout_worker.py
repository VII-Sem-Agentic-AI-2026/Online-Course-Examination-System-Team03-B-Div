import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.models import ExamAttempt
from backend.app.graph.exam_graph import evaluation_node
from backend.app.api import _save_state


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# PROCESS EXPIRED EXAM ATTEMPTS
# ============================================================

def run_once():
    """
    Find expired exam attempts and automatically evaluate them.

    The database is the source of truth.
    The worker does not use the API's in-memory sessions dictionary.
    """

    now = datetime.now(timezone.utc)

    # --------------------------------------------------------
    # STEP 1: FIND EXPIRED ATTEMPTS
    # --------------------------------------------------------

    with SessionLocal() as db:

        expired_attempts = db.scalars(
            select(ExamAttempt).where(
                ExamAttempt.ends_at <= now
            )
        ).all()

        attempt_ids = [
            attempt.id
            for attempt in expired_attempts
            if (
                attempt.session_state
                and not attempt.session_state.get("final_result")
            )
        ]

    # --------------------------------------------------------
    # STEP 2: PROCESS EACH ATTEMPT
    # --------------------------------------------------------

    for sid in attempt_ids:

        try:

            # Fetch the latest state from PostgreSQL.
            with SessionLocal() as db:

                attempt = db.get(ExamAttempt, sid)

                if (
                    attempt is None
                    or not attempt.session_state
                    or attempt.session_state.get("final_result")
                ):
                    continue

                state = dict(attempt.session_state)

            # ------------------------------------------------
            # STEP 3: CHECK SESSION STATUS
            # ------------------------------------------------

            session = dict(
                state.get("exam_session") or {}
            )

            status = str(
                session.get("status") or ""
            ).lower()

            if status not in {
                "in_progress",
                "expired",
                "submitted",
            }:
                logger.info(
                    "Skipping attempt %s. Status: %s",
                    sid,
                    status,
                )
                continue

            # ------------------------------------------------
            # STEP 4: MARK SESSION AS EXPIRED
            # ------------------------------------------------

            if status == "in_progress":

                session["status"] = "expired"

                state["exam_session"] = session

                _save_state(state)

                logger.info(
                    "Attempt %s marked as expired.",
                    sid,
                )

            # ------------------------------------------------
            # STEP 5: RUN EVALUATION
            # ------------------------------------------------

            logger.info(
                "Starting automatic evaluation for attempt %s.",
                sid,
            )

            evaluation = evaluation_node(state)

            # ------------------------------------------------
            # STEP 6: CHECK EVALUATION RESULT
            # ------------------------------------------------

            if (
                evaluation.get("current_stage") == "error"
                or not evaluation.get("final_result")
            ):

                logger.error(
                    "Evaluation failed for attempt %s: %s",
                    sid,
                    evaluation.get("last_error")
                    or evaluation.get("errors"),
                )

                continue

            # ------------------------------------------------
            # STEP 7: UPDATE AND SAVE STATE
            # ------------------------------------------------

            state.update(evaluation)

            _save_state(state)

            logger.info(
                "Successfully evaluated attempt %s.",
                sid,
            )

        except Exception:

            logger.exception(
                "Error processing attempt %s.",
                sid,
            )


# ============================================================
# WORKER LOOP
# ============================================================

if __name__ == "__main__":

    logger.info(
        "ExamPilot timeout worker started."
    )

    while True:

        try:
            run_once()

        except Exception:

            logger.exception(
                "Unexpected error in timeout worker."
            )

        time.sleep(30)