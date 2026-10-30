from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key, settings_dependency
from backend.config import Settings
from backend.database import get_db
from backend.schemas.assistant import AskRequest, AskResponse
from backend.services.assistant_service import answer_question
from backend.services.gemini_service import get_llm_client

router = APIRouter(prefix="/api/assistant", tags=["assistant"], dependencies=[Depends(require_api_key)])


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    return answer_question(db, request.question.strip(), settings, get_llm_client(settings))
