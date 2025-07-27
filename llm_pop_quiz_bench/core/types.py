from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    id: str
    provider: str
    model: str
    apiKeyEnv: str
    defaultParams: dict[str, object] = field(default_factory=dict)
    maxConcurrency: int = 1


@dataclass
class QuizOption:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    score: int | None = None


@dataclass
class QuizQuestion:
    id: str
    text: str
    options: list[QuizOption]


@dataclass
class OutcomeRule:
    id: str
    condition: dict[str, object]
    result: str


@dataclass
class QuizDefinition:
    id: str
    title: str
    source: dict[str, str]
    notes: str
    questions: list[QuizQuestion]
    outcomes: list[OutcomeRule]


@dataclass
class QAResult:
    question_id: str
    choice: str
    reason: str
    refused: bool = False
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


@dataclass
class ModelOutcomeSummary:
    model_id: str
    outcome: str
