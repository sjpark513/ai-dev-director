"""AI 역할들이 주고받는 데이터 형식(계약서).

원본: schemas/*.py (파일 5개) → 학습하기 쉽게 한 파일로 모았습니다.

AI CLI가 돌려주는 텍스트는 믿을 수 없으므로, 반드시 이 모델로 검증한 뒤에만 사용합니다.
검증에 실패하면 그 단계는 실패로 처리합니다(fail-closed).

흐름: HEAD → Order → BUILDER → BuilderResult → REVIEWER → ReviewResult → HEAD → Decision
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    # AI가 모르는 키를 덧붙여도 받아 줍니다(무시). 대신 필수 키와 타입은 엄격히 봅니다.
    model_config = ConfigDict(extra="ignore")


class Order(_Strict):
    """HEAD가 쓰는 작업 지시서. Director는 이 범위 밖의 변경을 거부합니다(3단계 Scope Guard)."""

    goal: str = Field(..., min_length=1, description="이번 작업의 목표")
    allowed_paths: List[str] = Field(default_factory=list, description="수정해도 되는 경로 (glob 허용: src/**)")
    protected_paths: List[str] = Field(default_factory=list, description="절대 건드리면 안 되는 경로")
    required_outputs: List[str] = Field(default_factory=list, description="반드시 만들어져야 하는 파일")
    acceptance_criteria: List[str] = Field(default_factory=list, description="완료 기준")
    reference_paths: List[str] = Field(default_factory=list, description="읽기 전용 참고 문서(절대 경로)")
    allowed_deletions: List[str] = Field(default_factory=list, description="삭제를 명시적으로 허락한 대상")
    max_files_changed: int = Field(default=15, ge=1)
    max_diff_lines: int = Field(default=800, ge=1)
    context: Optional[str] = None
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    requires_human_approval: bool = False


class BuilderResult(_Strict):
    """BUILDER 단계의 결과 요약. 실제 파일 내용 제안은 6~7단계에서 따로 다룹니다."""

    status: Literal["COMPLETED", "FAILED"]
    files_modified: List[str] = Field(default_factory=list)
    commands_run: List[str] = Field(default_factory=list)
    summary: str
    error: Optional[str] = None


class ReviewResult(_Strict):
    """REVIEWER의 독립 검토. p0=치명, p1=중요, p2=사소."""

    verdict: Literal["pass", "changes_required"]
    p0: List[str] = Field(default_factory=list)
    p1: List[str] = Field(default_factory=list)
    p2: List[str] = Field(default_factory=list)
    summary: str


class Decision(_Strict):
    """HEAD의 최종 판정. PASS라도 Director의 최종 게이트(6단계)를 다시 통과해야 합니다."""

    decision: Literal["PASS", "FAIL", "HUMAN_REQUIRED"]
    rationale: str
    next_steps: List[str] = Field(default_factory=list)


class Provenance(BaseModel):
    """어떤 CLI가 언제 어떻게 실행됐는지에 대한 기록.

    observed(실제로 측정한 값)와 declared(정책상 주장일 뿐인 값)를 구분해 둡니다.
    예: api_key_used=False는 "환경변수에서 키를 지웠다"는 뜻이지, 실제 과금 방식을 확인한 값이 아닙니다.
    """

    role: Literal["HEAD", "BUILDER", "REVIEWER"]
    provider: str
    executable: str
    argv: List[str]
    timestamp: str
    # observed
    exit_code: Optional[int] = None
    duration_sec: Optional[float] = None
    timed_out: bool = False
    # declared
    api_key_used: bool = False
