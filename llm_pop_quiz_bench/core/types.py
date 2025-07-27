from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ModelConfig:
    id: str
    provider: str
    model: str
    apiKeyEnv: str
    defaultParams: Dict[str, object] = field(default_factory=dict)
    maxConcurrency: int = 1


@dataclass
class QuizOption:
    id: str
    text: str
    tags: List[str] = field(default_factory=list)
    score: Optional[int] = None


@dataclass
class QuizQuestion:
    id: str
    text: str
    options: List[QuizOption]


@dataclass
class OutcomeRule:
    id: str
    condition: Dict[str, object]
    result: str


@dataclass
class QuizDefinition:
    id: str
    title: str
    source: Dict[str, str]
    notes: str
    questions: List[QuizQuestion]
    outcomes: List[OutcomeRule]


@dataclass
class QAResult:
    question_id: str
    choice: str
    reason: str
    refused: bool = False
    latency_ms: Optional[int] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


@dataclass
class ModelOutcomeSummary:
    model_id: str
    outcome: str
