# Incrément 2 — Brief généré + personas (`feat/advisor-brief`)

> **Pour les workers agentiques :** SOUS-SKILL REQUISE — `superpowers:executing-plans` ou `superpowers:subagent-driven-development`. Étapes en cases (`- [ ]`).

**Objectif :** un bouton « Générer le plan d'action » sur une nouvelle vue `/conseiller` qui appelle Claude (Opus 5) avec les données d'audit du site + une persona choisie, et affiche un brief markdown priorisé. POST bloquant (~20-40 s), pas de streaming.

**Architecture :** `app/services/advisor/` (personas, context_builder, llm, service) sur le motif ABC+Real+Mock injecté via `deps.py` (comme `AuditProbe`/`GoogleOAuthClient`). 4 nouvelles tables. Endpoints REST sous `/advisor`. Frontend : vue cliente, `react-markdown`, sélecteur de persona.

**Tech Stack :** `anthropic` SDK Python (nouveau), FastAPI async, SQLAlchemy 2.0 / Alembic, pytest `-W error` ; Next.js 16 / React 19, `react-markdown` + `remark-gfm` (nouveaux).

**Spec :** `docs/superpowers/specs/2026-09-10-advisor-agent-gtm-check-design.md` §5 (mise à jour 2026-09-10 : brief en POST bloquant).

## Contraintes globales

- **Lecture seule vers l'extérieur.** Le seul appel réseau est vers l'API Anthropic. Aucun outil, aucune écriture Google.
- **Le prompt persona s'ajoute, ne remplace pas** `SYSTEM_BASE`.
- **Coût borné** : `advisor_daily_brief_cap` (défaut 5 / utilisateur / jour) → `429`. `usage` (tokens) persisté par message.
- **`RealAdvisorLLM` non couvert par CI** — politique existante `RealGoogleOAuthClient`. La suite tourne avec `MockAdvisorLLM` (`advisor_mock=True`, défaut).
- **Modèle** : `claude-opus-5` exactement (pas de suffixe date). `thinking={"type":"adaptive"}`, `output_config={"effort":"high"}`, `max_tokens=8000`, `async with client.messages.stream(...) as s: await s.get_final_message()`. Pas de prefill. `budget_tokens` interdit.
- **Colonnes `role`/`status`** : `String` simple (pas de `pg_enum`, pas de `CheckConstraint`) — valeurs 100 % contrôlées par le code, jamais saisies. Évite toute question de dérive de contrainte / garde-fou `test_enum_check_*`.
- **ruff** `select = [...]` inchangé, `line-length = 100`. `ruff format` non vérifié en CI.
- **Front** : `next build` + `eslint --max-warnings 0` = non-régression (pas de tests unitaires front).
- Migration : `down_revision = "0c6d572e41fe"`. `alembic check` doit rester propre (`test_models_match_migration`).

---

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `backend/pyproject.toml` | **modifier** — dép `anthropic` |
| `backend/app/config.py` | **modifier** — `anthropic_api_key`, `advisor_*` |
| `backend/app/models/advisor.py` | **créer** — `AdvisorThread`, `AdvisorMessage`, `AdvisorUsage`, `UserAdvisorSettings` |
| `backend/app/models/__init__.py` | **modifier** — enregistrer les 4 modèles |
| `backend/alembic/versions/xxxx_advisor_tables.py` | **créer** — `create_table` ×4 |
| `backend/app/services/advisor/__init__.py` | **créer** |
| `backend/app/services/advisor/personas.py` | **créer** — presets + `build_system` |
| `backend/app/services/advisor/context_builder.py` | **créer** — `build_context` |
| `backend/app/services/advisor/llm.py` | **créer** — `AdvisorLLM`, `BriefResult`, `MockAdvisorLLM`, `RealAdvisorLLM` |
| `backend/app/services/advisor/service.py` | **créer** — `generate_brief`, `AdvisorCapReached` |
| `backend/app/api/deps.py` | **modifier** — `get_advisor_llm`, `AdvisorLLMDep` |
| `backend/app/api/v1/endpoints/advisor.py` | **créer** — 5 endpoints |
| `backend/app/api/v1/router.py` | **modifier** — monter `advisor.router` |
| `backend/tests/test_personas.py` | **créer** |
| `backend/tests/test_context_builder.py` | **créer** |
| `backend/tests/test_advisor_llm.py` | **créer** |
| `backend/tests/test_advisor_service.py` | **créer** |
| `backend/tests/test_advisor_endpoints.py` | **créer** |
| `backend/tests/test_migrations.py` | **modifier** — `EXPECTED_TABLES` += 4 |
| `frontend/package.json` | **modifier** — `react-markdown`, `remark-gfm` |
| `frontend/lib/api/dto.ts` | **modifier** — DTO advisor |
| `frontend/lib/api/advisor.ts` | **créer** — client + types |
| `frontend/lib/shell/routes.ts` | **modifier** — 6ᵉ route `/conseiller` |
| `frontend/app/(shell)/conseiller/page.tsx` | **créer** |
| `frontend/components/conseiller/advisor-view.tsx` | **créer** |
| `frontend/components/conseiller/persona-picker.tsx` | **créer** |
| `frontend/components/conseiller/brief-markdown.tsx` | **créer** |
| `frontend/components/overview/priority-recommendation.tsx` | **modifier** — lien vers `/conseiller` |

---

## Task 1 : dépendance `anthropic` + config

**Files:** `backend/pyproject.toml`, `backend/app/config.py`

- [ ] **Étape 1** — `pyproject.toml` `dependencies` : ajouter `"anthropic>=0.40"`. Puis `cd backend && ./.venv/Scripts/python.exe -m uv pip install anthropic` (ou `uv sync` si `uv` dispo ; sinon `./.venv/Scripts/pip.exe install "anthropic>=0.40"` et régénérer `uv.lock` avec `uv lock` quand possible). Vérifier : `./.venv/Scripts/python.exe -c "import anthropic; print(anthropic.__version__)"`.

- [ ] **Étape 2** — `app/config.py`, dans `Settings` après `pagespeed_api_key` :

```python
    # Clé API Anthropic pour l'agent conseiller. Vide -> MockAdvisorLLM force.
    anthropic_api_key: SecretStr = SecretStr("")
    # true -> MockAdvisorLLM (aucun appel reseau). Defaut : mode demo.
    advisor_mock: bool = True
    advisor_brief_model: str = "claude-opus-5"
    advisor_chat_model: str = "claude-sonnet-5"
    advisor_daily_brief_cap: int = 5
    advisor_daily_message_cap: int = 40      # incr. 3
    advisor_tool_iteration_cap: int = 6      # incr. 3
```

- [ ] **Étape 3** — `./.venv/Scripts/python.exe -m pytest tests/test_config.py -q` (si absent, `-c "from app.config import get_settings; get_settings()"`). ruff.

- [ ] **Étape 4 : commit** — `git commit -m "chore(advisor): dépendance anthropic + config"`

---

## Task 2 : modèles + migration

**Files:** `backend/app/models/advisor.py`, `backend/app/models/__init__.py`, `backend/alembic/versions/*_advisor_tables.py`, `backend/tests/test_migrations.py`

**Interfaces produites :**

```python
# app/models/advisor.py
class AdvisorThread(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "advisor_threads"
    website_id: Mapped[UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    persona_key: Mapped[str] = mapped_column(String(32))
    custom_prompt_snapshot: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200))
    source_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("audit_snapshots.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # archived_at -> incr. 3

class AdvisorMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "advisor_messages"
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("advisor_threads.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))          # "user" | "assistant"
    blocks: Mapped[list] = mapped_column(JSONB)            # tableau de content blocks (replay API)
    text: Mapped[str] = mapped_column(Text)               # aplati
    usage: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))        # "complete" | "error" (+ "streaming" incr. 3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # tool_log -> incr. 3

class AdvisorUsage(Base):
    __tablename__ = "advisor_usage"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    brief_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

class UserAdvisorSettings(Base):
    __tablename__ = "user_advisor_settings"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    persona_key: Mapped[str] = mapped_column(String(32), default="consultant", server_default="consultant")
    custom_prompt: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

`JSONB` : `from sqlalchemy.dialects.postgresql import JSONB`. `Date` de `sqlalchemy`.

- [ ] **Étape 1** — écrire `app/models/advisor.py` + ajouter les 4 classes à `app/models/__init__.py` (import + `__all__`).

- [ ] **Étape 2** — générer la migration :
```bash
cd backend
ALEMBIC_DATABASE_URL=<database_url> ./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "advisor tables"
```
Relire le fichier généré : 4 `op.create_table`, `down_revision = "0c6d572e41fe"`, `downgrade` = 4 `op.drop_table` dans l'ordre inverse. Retirer tout `op.` parasite touchant d'autres tables.

- [ ] **Étape 3** — appliquer aux 2 bases :
```bash
ALEMBIC_DATABASE_URL=<control_center>            ./.venv/Scripts/python.exe -m alembic upgrade head
ALEMBIC_DATABASE_URL=<control_center_migrations> ./.venv/Scripts/python.exe -m alembic upgrade head
```

- [ ] **Étape 4** — `tests/test_migrations.py` : `EXPECTED_TABLES` += `"advisor_threads"`, `"advisor_messages"`, `"advisor_usage"`, `"user_advisor_settings"`.

- [ ] **Étape 5** — `./.venv/Scripts/python.exe -m pytest tests/test_migrations.py tests/test_enum_check_constraints.py -q` → vert (dont `test_models_match_migration` = `alembic check` propre, et le garde-fou enum inchangé). Roundtrip manuel : `alembic downgrade -1 && alembic upgrade head` sur la base migrations.

- [ ] **Étape 6 : commit** — `git commit -m "feat(advisor): 4 tables (threads, messages, usage, settings) + migration"`

---

## Task 3 : `personas.py`

**Files:** `backend/app/services/advisor/__init__.py` (vide ou ré-exports), `backend/app/services/advisor/personas.py`, `backend/tests/test_personas.py`

**Interfaces produites :**
```python
PERSONA_PRESETS: dict[str, str]          # clé -> texte d'instructions
PERSONA_DEFAULT = "consultant"
CUSTOM_PROMPT_MAX = 2000
def build_system(persona_key: str, custom_prompt: str | None) -> list[dict]
def validate_custom_prompt(value: str) -> str   # trim, <= 2000, non vide -> sinon ValueError
```

`SYSTEM_BASE` (constante, français) doit contenir : le rôle (consultant marketing/analytics qui lit un diagnostic technique), le **squelette de sortie figé** (`## Synthèse` / `## Actions prioritaires` / `## Sous surveillance` / `## Données manquantes`, chaque action = quoi / pourquoi chiffré / comment démarrer / effort), la consigne « les données fournies sont un instantané d'audit — n'invente aucun chiffre absent », et « réponds en français, en markdown ».

`build_system` renvoie :
```python
[
    {"type": "text", "text": SYSTEM_BASE, "cache_control": {"type": "ephemeral"}},
    {"type": "text",
     "text": "Style et priorités demandés par l'utilisateur :\n" + persona_text,
     "cache_control": {"type": "ephemeral"}},
]
```
où `persona_text = custom_prompt` si `persona_key == "custom"` sinon `PERSONA_PRESETS[persona_key]` (fallback `PERSONA_PRESETS[PERSONA_DEFAULT]` si clé inconnue).

- [ ] **Étape 1 : test qui échoue** — `tests/test_personas.py`

```python
import pytest
from app.services.advisor.personas import (
    PERSONA_DEFAULT, PERSONA_PRESETS, build_system, validate_custom_prompt,
)


def test_presets_cover_the_four_documented_keys() -> None:
    assert {"consultant", "pedagogue", "growth", "technique"} <= set(PERSONA_PRESETS)
    assert PERSONA_DEFAULT in PERSONA_PRESETS


def test_build_system_keeps_base_and_appends_persona() -> None:
    blocks = build_system("technique", None)
    assert len(blocks) == 2
    assert "Synthèse" in blocks[0]["text"]            # squelette figé présent
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert PERSONA_PRESETS["technique"] in blocks[1]["text"]


def test_custom_prompt_is_appended_not_replacing_base() -> None:
    blocks = build_system("custom", "Parle comme un pirate.")
    assert "Synthèse" in blocks[0]["text"]
    assert "pirate" in blocks[1]["text"]


def test_unknown_key_falls_back_to_default() -> None:
    assert PERSONA_PRESETS[PERSONA_DEFAULT] in build_system("bogus", None)[1]["text"]


def test_validate_custom_prompt() -> None:
    assert validate_custom_prompt("  hello  ") == "hello"
    with pytest.raises(ValueError):
        validate_custom_prompt("   ")
    with pytest.raises(ValueError):
        validate_custom_prompt("x" * 2001)
```

- [ ] **Étape 2** — lancer → échec.
- [ ] **Étape 3** — implémenter.
- [ ] **Étape 4** — vert + ruff.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): personas (presets + prompt éditable, base figée)"`

---

## Task 4 : `context_builder.py`

**Files:** `backend/app/services/advisor/context_builder.py`, `backend/tests/test_context_builder.py`

**Interface produite :** `async def build_context(session: AsyncSession, website: Website) -> str` — renvoie un JSON **trié par clés** (`json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)`).

Contenu (cf. spec §5.4) : `site` (domain, display_name, detected_stack, stack_label, ssl_status, ssl_expires_at iso) ; `latest_snapshot` (captured_at iso, `scores` {ga4,gsc,cwv}, `cwv` {lcp_ms,inp_ms,cls,field_data}, `ga4` {degraded, purchase_missing_params, missing_events}, `gsc` {degraded, valid_pages, excluded_pages, noindex_pages, connection_stale_days}, `gtm` = bloc résumé : containers, snippet_form, consent_platform, findings[code+severity+title]) ; `open_issues` (liste {title, category, severity, status, detected_at iso} — `IssueItem` where status in todo/in_progress, triées sévérité desc) ; `score_history` (8 derniers `AuditSnapshot` → {date, ga4, gsc, cwv}) ; `data_gaps` (liste : `"ga4_disconnected"` si `ga4.degraded`/score 0, `"gsc_disconnected"` idem, `"no_snapshot"` si aucun).

Pas les gros tableaux bruts (`costly_entities`, `lcp_assets`, `sample_urls`).

- [ ] **Étape 1 : test qui échoue** — `tests/test_context_builder.py`

```python
import json
from datetime import UTC, datetime

from app.models.audit_snapshot import AuditSnapshot
from app.models.enums import IssueCategory, IssueSeverity, IssueStatus, SnapshotSource
from app.models.issue_item import IssueItem
from app.models.website import Website
from app.services.advisor.context_builder import build_context
from tests.conftest import UserFactory


async def _site(db_session, user_id) -> Website:
    site = Website(user_id=user_id, domain="ctx.test", display_name="Ctx", detected_stack=None)
    db_session.add(site); await db_session.flush()
    return site


async def test_context_is_deterministic_sorted_json(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="ctx-1")
    site = await _site(db_session, user.id)
    db_session.add(AuditSnapshot(
        website_id=site.id, captured_at=datetime(2026, 9, 1, tzinfo=UTC),
        source=SnapshotSource.COMPOSITE,
        metrics={"ga4": {"score": 40, "degraded": True}, "gsc": {"score": 88},
                 "cwv": {"score": 70, "lcp_ms": 3000, "inp_ms": 150, "cls": 0.05},
                 "gtm": {"containers": ["GTM-X"], "snippet_form": "standard",
                         "consent_platform": None, "findings": []}},
    ))
    db_session.add(IssueItem(
        website_id=site.id, title="purchase params", description="...",
        category=IssueCategory.ANALYTICS, severity=IssueSeverity.CRITICAL,
        status=IssueStatus.TODO, fingerprint="f" * 64, detected_at=datetime(2026, 9, 1, tzinfo=UTC),
    ))
    await db_session.flush()

    raw = await build_context(db_session, site)
    assert raw == json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False, indent=2)
    data = json.loads(raw)
    assert data["site"]["domain"] == "ctx.test"
    assert data["latest_snapshot"]["scores"] == {"ga4": 40, "gsc": 88, "cwv": 70}
    assert data["latest_snapshot"]["gtm"]["containers"] == ["GTM-X"]
    assert data["open_issues"][0]["title"] == "purchase params"
    assert "ga4_disconnected" in data["data_gaps"]


async def test_context_without_snapshot_flags_gap(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="ctx-2")
    site = await _site(db_session, user.id)
    data = json.loads(await build_context(db_session, site))
    assert data["latest_snapshot"] is None
    assert "no_snapshot" in data["data_gaps"]
```

- [ ] **Étapes 2-4** — échec → implémenter → vert + ruff.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): context_builder (JSON déterministe du diagnostic)"`

---

## Task 5 : `llm.py`

**Files:** `backend/app/services/advisor/llm.py`, `backend/tests/test_advisor_llm.py`

**Interfaces produites :**
```python
@dataclass(frozen=True, slots=True)
class BriefResult:
    text: str
    usage: dict            # {"input": int, "output": int, "cache_read": int, "cache_creation": int}

class AdvisorLLM(abc.ABC):
    @abc.abstractmethod
    async def generate_brief(self, *, system: list[dict], context: str,
                             max_tokens: int = 8000) -> BriefResult: ...

class MockAdvisorLLM(AdvisorLLM):
    def __init__(self, *, text: str | None = None) -> None: ...
    # renvoie un markdown fixe plausible (les 4 sections) + usage à 0

class RealAdvisorLLM(AdvisorLLM):
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
    async def generate_brief(self, *, system, context, max_tokens=8000) -> BriefResult:
        async with self._client.messages.stream(
            model=self._model, max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            messages=[{"role": "user", "content":
                       context + "\n\nGénère le plan d'action priorisé."}],
        ) as stream:
            msg = await stream.get_final_message()
        text = "".join(b.text for b in msg.content if b.type == "text")
        u = msg.usage
        return BriefResult(text=text, usage={
            "input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
        })
```

- [ ] **Étape 1 : test** — `tests/test_advisor_llm.py` : `MockAdvisorLLM().generate_brief(...)` renvoie un `BriefResult` dont `text` contient `## Synthèse` et `usage` a les 4 clés à 0. `MockAdvisorLLM(text="X").generate_brief(...)` renvoie `"X"`. (Pas de test de `RealAdvisorLLM` — noté hors CI.)

- [ ] **Étapes 2-4** — échec → implémenter → vert + ruff.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): abstraction LLM (ABC + Mock + Real Anthropic)"`

---

## Task 6 : `service.py` (orchestration)

**Files:** `backend/app/services/advisor/service.py`, `backend/tests/test_advisor_service.py`

**Interfaces produites :**
```python
class AdvisorCapReached(Exception): ...

@dataclass(frozen=True, slots=True)
class BriefOutcome:
    thread_id: UUID
    message_id: UUID
    content: str
    usage: dict

async def generate_brief(
    session: AsyncSession, *, website: Website, user_id: UUID,
    llm: AdvisorLLM, daily_cap: int,
) -> BriefOutcome
```

Logique : cf. draft §5.6 spec — cap check via `AdvisorUsage` (upsert `(user_id, day)`), lit `UserAdvisorSettings` (défaut `PERSONA_DEFAULT`), `build_system` + `build_context`, `await llm.generate_brief(...)`, crée `AdvisorThread` (`title=f"Plan d'action — {today}"`, `source_snapshot_id`=dernier snapshot) + `AdvisorMessage` (`role="assistant"`, `blocks=[{"type":"text","text":text}]`, `text`, `usage`, `status="complete"`), `usage_row.brief_count += 1`, `flush`. **Ne commit pas** (l'endpoint commit).

- [ ] **Étape 1 : tests** — `tests/test_advisor_service.py`
  - `test_generate_brief_persists_thread_message_and_usage` : monte user + site + 1 snapshot ; `generate_brief(..., llm=MockAdvisorLLM(), daily_cap=5)` → `AdvisorThread` + `AdvisorMessage(status="complete", text contient "## Synthèse")` en base, `AdvisorUsage.brief_count == 1`, `BriefOutcome` cohérent.
  - `test_second_call_increments_usage` : 2 appels → `brief_count == 2`.
  - `test_cap_reached_raises` : `daily_cap=1`, 2ᵉ appel → `AdvisorCapReached`, aucune 2ᵉ ligne thread.
  - `test_uses_saved_persona` : insère `UserAdvisorSettings(persona_key="technique")` → `thread.persona_key == "technique"`.
  - `test_llm_error_propagates_nothing_persisted` : `MockAdvisorLLM` configuré pour lever → exception remonte, 0 thread.

- [ ] **Étapes 2-4** — échec → implémenter → vert + ruff.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): service generate_brief (cap, persona, persistance)"`

---

## Task 7 : `deps.py` + endpoints + router

**Files:** `backend/app/api/deps.py`, `backend/app/api/v1/endpoints/advisor.py`, `backend/app/api/v1/router.py`, `backend/tests/test_advisor_endpoints.py`

**`deps.py` :**
```python
from app.services.advisor.llm import AdvisorLLM, MockAdvisorLLM, RealAdvisorLLM

def get_advisor_llm(settings: SettingsDep) -> AdvisorLLM:
    key = settings.anthropic_api_key.get_secret_value()
    if settings.advisor_mock or not key:
        return MockAdvisorLLM()
    return RealAdvisorLLM(api_key=key, model=settings.advisor_brief_model)

AdvisorLLMDep = Annotated[AdvisorLLM, Depends(get_advisor_llm)]
```

**Endpoints `advisor.py`** (`router = APIRouter(tags=["advisor"])`, `_owned_website` copié de `websites.py` ou importé) :

| méthode | route | corps / réponse |
|---|---|---|
| `GET` | `/advisor/settings` | → `{persona_key, custom_prompt, presets: [{key, label}]}` (crée la ligne défaut si absente, ou renvoie défaut sans écrire) |
| `PUT` | `/advisor/settings` | `{persona_key: str, custom_prompt: str \| None}` → upsert. `persona_key` ∉ presets ∪ {"custom"} → 422 ; `"custom"` sans prompt valide → 422 (`validate_custom_prompt`). |
| `POST` | `/websites/{id}/advisor/brief` | ownership → `try: generate_brief(...) ; await session.commit()` → `{thread_id, message_id, content, usage}` ; `AdvisorCapReached` → `429` ; `anthropic.APIError` / `Exception` du LLM → `502` « le conseiller n'a pas pu répondre » (pas de commit). |
| `GET` | `/websites/{id}/advisor/threads` | ownership → `[{id, title, created_at, message_count}]` tri `created_at` desc |
| `GET` | `/advisor/threads/{id}` | ownership via `thread.website_id` → `{id, title, persona_key, created_at, messages: [{id, role, text, usage, created_at}]}` |

`router.py` : `from app.api.v1.endpoints import advisor` + `api_router.include_router(advisor.router)`.

- [ ] **Étape 1 : tests** — `tests/test_advisor_endpoints.py`, fixture `mock_advisor` override `get_advisor_llm` → `MockAdvisorLLM()` (défaut suffit mais explicite = robuste). Cas :
  - `GET /advisor/settings` sans ligne → `persona_key == "consultant"`, `presets` non vide.
  - `PUT` persona valide → persistée ; `PUT {persona_key:"custom", custom_prompt:""}` → 422 ; `PUT {persona_key:"zzz"}` → 422.
  - `POST /websites/{id}/advisor/brief` → 200, `content` contient `## Synthèse`, un thread listé par `GET .../threads`, `GET /advisor/threads/{tid}` renvoie le message assistant.
  - cap : `PUT` config non nécessaire ; boucler `advisor_daily_brief_cap` (5) POST puis le 6ᵉ → 429. *(ou fixture qui patche `settings.advisor_daily_brief_cap = 1`)*
  - erreur LLM → override `get_advisor_llm` avec un mock qui lève → 502, `GET .../threads` vide.
  - `test_endpoints_require_auth` : les 5 routes sans cookie → 401.
  - ownership : site d'un autre user → 404.

- [ ] **Étapes 2-4** — échec → implémenter → vert. **Suite complète** `./.venv/Scripts/python.exe -m pytest -W error -q` → tout vert. ruff `app tests`.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): endpoints REST (settings, brief, threads)"`

---

## Task 8 : frontend — client API + dépendance markdown

**Files:** `frontend/package.json`, `frontend/lib/api/dto.ts`, `frontend/lib/api/advisor.ts`

- [ ] **Étape 1** — `cd frontend && npm install react-markdown remark-gfm`.

- [ ] **Étape 2** — `dto.ts` :
```ts
export interface AdvisorPresetDto { key: string; label: string; }
export interface AdvisorSettingsDto {
  persona_key: string; custom_prompt: string | null; presets: AdvisorPresetDto[];
}
export interface AdvisorBriefDto {
  thread_id: string; message_id: string; content: string;
  usage: { input: number; output: number; cache_read: number; cache_creation: number };
}
export interface AdvisorThreadSummaryDto {
  id: string; title: string; created_at: string; message_count: number;
}
export interface AdvisorMessageDto {
  id: string; role: "user" | "assistant"; text: string;
  usage: AdvisorBriefDto["usage"] | null; created_at: string;
}
export interface AdvisorThreadDto {
  id: string; title: string; persona_key: string; created_at: string;
  messages: AdvisorMessageDto[];
}
```

- [ ] **Étape 3** — `lib/api/advisor.ts` :
```ts
import { apiGet, apiPost, apiPut } from "./client";
// ... fetchAdvisorSettings(), saveAdvisorSettings(body),
//     generateBrief(websiteId), fetchThreads(websiteId), fetchThread(threadId)
```
> `apiPut` n'existe pas encore dans `client.ts` — l'ajouter (calque de `apiPatch`).
> `generateBrief` : `apiPost` avec un timeout client généreux. `client.ts` `request` n'expose pas de timeout → ajouter `AbortSignal.timeout(90_000)` dans `generateBrief` uniquement (ou passer `signal` en option de `request`).

- [ ] **Étape 4** — `npm run lint` (les nouveaux fichiers ne sont pas encore importés → build OK).
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): client API frontend + react-markdown"`

---

## Task 9 : frontend — vue `/conseiller`

**Files:** `frontend/lib/shell/routes.ts`, `frontend/app/(shell)/conseiller/page.tsx`, `frontend/components/conseiller/*`, `frontend/components/overview/priority-recommendation.tsx`

- [ ] **Étape 1** — `routes.ts` : importer une icône lucide **hors** `Sparkles` (DA) — `MessageSquareText` ou `Compass`. Ajouter en 6ᵉ position :
```ts
{ href: "/conseiller", label: "Conseiller", crumb: "Conseiller", icon: MessageSquareText },
```

- [ ] **Étape 2** — `app/(shell)/conseiller/page.tsx` : `export default function Page() { return <AdvisorView />; }` (`"use client"` dans `AdvisorView`).

- [ ] **Étape 3** — `components/conseiller/brief-markdown.tsx` : wrappe `react-markdown` + `remark-gfm` avec un `components` map (h2 → `text-sm font-medium text-ink mt-5`, ul → `list-disc pl-5 space-y-1 text-sm text-ink-muted`, li, strong → `text-ink font-medium`, code → `font-mono text-2xs bg-white/[0.06] px-1 rounded`, p → `text-sm leading-relaxed text-ink-muted`). Pas de `@tailwindcss/typography`.

- [ ] **Étape 4** — `components/conseiller/persona-picker.tsx` : `<select>` des `presets` + option « Personnalisé ». Si `custom` → `<textarea>` (maxLength 2000). `onBlur` → `saveAdvisorSettings`. Toast succès/erreur (sonner). Style : tokens `/audit` existants.

- [ ] **Étape 5** — `components/conseiller/advisor-view.tsx` :
  - `const { workspace } = useShell();`
  - si `workspace.websiteId == null` → encart « Ajoute d'abord un vrai site pour générer un plan » (le conseiller a besoin d'un diagnostic réel).
  - `useEffect` (IIFE async, motif `stack-picker-dialog.tsx` pour éviter `react-hooks/set-state-in-effect`) : charge `fetchAdvisorSettings()` + `fetchThreads(websiteId)`.
  - `<PersonaPicker .../>`.
  - Bouton « Générer le plan d'action » : `disabled` pendant l'appel ; état `loading` → spinner + « Analyse en cours… (jusqu'à 40 s) ». `generateBrief` → prepend au state threads + affiche `content` via `<BriefMarkdown>`. Erreur → toast (`ApiError.message`, 429 = message de cap, 502 = « réessaie »).
  - Liste des briefs passés (`threads`) : clic → `fetchThread` → affiche le markdown stocké.
  - `key={workspace.id}` sur la sous-vue à état (reset au changement de site).

- [ ] **Étape 6** — `priority-recommendation.tsx` : sous le bouton CTA, un lien discret `Link href="/conseiller"` « Voir le plan d'action complet → ». Garder le reste.

- [ ] **Étape 7** — `cd frontend && npm run build && npm run lint` → 0 / 0.

- [ ] **Étape 8 : vérif navigateur** — preview, `/conseiller` sur un site démo réel (les 4 sites du seed ont un `websiteId`) : la vue charge, le sélecteur de persona s'affiche, « Générer » appelle l'API (backend en `advisor_mock=true` par défaut → `MockAdvisorLLM`, réponse immédiate), le brief markdown s'affiche, un thread apparaît dans la liste. Console sans erreur. Screenshot.

- [ ] **Étape 9 : commit** — `git commit -m "feat(advisor): vue /conseiller (persona + brief généré)"`

---

## Task 10 : commit spec/plan + contrôle santé + smoke test réel

- [ ] **Étape 1** — `git add docs/superpowers/plans/2026-09-11-advisor-brief.md && git commit -m "docs: plan incrément 2 (advisor brief)"`

- [ ] **Étape 2 : contrôle santé**
  - `cd backend && ./.venv/Scripts/python.exe -m pytest -W error -q` → tout vert, 0 flake (relancer `test_advisor_*` `test_personas` `test_context_builder` 2×).
  - `cd frontend && npm run build && npm run lint` → 0 / 0.
  - `git status` propre. `alembic check` propre.

- [ ] **Étape 3 : smoke test avec la vraie API (hors CI, documenté)**
  - `backend/.env` : `ANTHROPIC_API_KEY=sk-ant-...` + `ADVISOR_MOCK=false`.
  - Redémarrer le backend. Sur `/conseiller` d'un vrai site (qaopscareer.com si ajouté), choisir la persona « consultant », « Générer ».
  - Attendre ~20-40 s → vérifier que le brief a les 4 sections, cite des chiffres réels du diagnostic, et que `usage` est non nul (visible en base : `select usage from advisor_messages`).
  - Générer 5×, vérifier le `429` au 6ᵉ.
  - Remettre `ADVISOR_MOCK=true` (ou retirer la clé) après le test.
  - Noter le coût observé (tokens in/out) pour calibrer `advisor_daily_brief_cap`.

---

## Self-review (writing-plans)

- **Couverture spec §5** : config (T1), tables+migration (T2), personas §5.2/5.3 (T3), context §5.4 (T4), LLM §5.1 (T5), service §5.6/5.7 (T6), endpoints §5.8 + deps §5.1 (T7), frontend §5.10 (T8-9). Prompt caching §5.5 = `cache_control` posé dans `build_system` (T3). ✔
- **Placeholders** : `SYSTEM_BASE` non écrit mot à mot mais son contrat (4 sections, consignes) est fixé + testé (`"Synthèse" in blocks[0]["text"]`). Les `<database_url>` des commandes alembic = valeurs de `backend/.env` (`database_url`, `database_url_migrations_test`).
- **Cohérence de types** : `BriefResult`(T5) → `BriefOutcome`(T6) → `AdvisorBriefDto`(T8) ; `persona_key`/`status`/`role` = `str` partout ; `usage` = même dict 4-clés backend→DTO.
- **Périmètre** : 10 tâches, chacune testable/commit ; pas de streaming (POST bloquant), pas d'outils, pas de chat, pas de headless — tout ça = incr. 3.
- **Risques** : (a) transaction DB ouverte ~30 s pendant l'appel LLM — acceptable pour un outil solo faible volume ; (b) `output_config`/`thinking` : si l'API 400 sur un paramètre, ajuster selon le message (le skill claude-api est la référence — `effort` dans `output_config`, `thinking:{type:"adaptive"}`, jamais `budget_tokens`) ; (c) `react-markdown` rend du markdown généré par un LLM sur nos propres données — pas d'entrée utilisateur tierce, XSS non applicable (react-markdown échappe le HTML par défaut, ne pas activer `rehype-raw`).
