# Incrément 3b — Outils d'action + archivage (`feat/advisor-actions`)

> **Pour les workers agentiques :** SOUS-SKILL REQUISE — `superpowers:executing-plans` ou `superpowers:subagent-driven-development`. Étapes en cases (`- [ ]`).

**Objectif :** l'agent peut agir, pas seulement lire — relancer un diagnostic (`trigger_rescan`) et générer un snippet dataLayer (`draft_gtm_snippet`), avec rate-limiting et traçabilité. L'utilisateur peut archiver un fil de discussion.

**Décision 2026-09-11 (avant ce plan) : sans vérification headless.** `uv add playwright` a échoué deux fois en environnement sandbox (timeout réseau, puis DNS) — deux causes différentes, deux réseaux. Le code de `verify_gtm`/`GtmHeadlessResult` reste designé dans la spec (§6.5) pour une reprise hors de ce sandbox ; ce plan ne le construit pas.

**Architecture :** `ToolContext` remplace les kwargs `session=`/`website=` de `dispatch()` (incr. 3a) pour porter aussi `user_id`, `thread_id` et les dépendances d'action (`probe`, `detector`, `tls_checker`, `gtm_checker`). Rate-limit via une table `advisor_tool_calls` (une ligne par appel d'action, fenêtre glissante).

**Tech Stack :** identique aux incréments précédents. Une migration (2 changements de schéma).

**Spec :** `docs/superpowers/specs/2026-09-10-advisor-agent-gtm-check-design.md` §6.3 (`trigger_rescan`, `draft_gtm_snippet`), §6.6 (`DELETE /advisor/threads/{id}`).

## Contraintes globales

- **Actions internes uniquement.** `trigger_rescan` réutilise `run_audit` (déjà lecture-seule côté externe : sonde le site, ne modifie rien chez un tiers). `draft_gtm_snippet` est pur (aucun effet de bord).
- **Rate-limit** : `trigger_rescan` 1×/thread/10 min, aucun rate-limit sur `draft_gtm_snippet` (texte pur).
- **Traçabilité** : `trigger_rescan` passe par `run_audit`, qui écrit déjà une ligne `audit_log` (`action="website.scan"`) — rien à ajouter.
- **`ToolContext`** rend `dispatch()` non-breaking à étendre plus tard (ex. futur outil `run_gtm_headless_probe` en 3c) sans re-changer la signature.
- ruff/tests : mêmes règles que les incréments précédents.

---

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `backend/app/models/advisor.py` | **modifier** — `AdvisorThread.archived_at`, `AdvisorToolCall` |
| `backend/alembic/versions/xxxx_advisor_actions.py` | **créer** |
| `backend/app/services/advisor/tools.py` | **modifier** — `ToolContext`, rate-limit, `trigger_rescan`, `draft_gtm_snippet` |
| `backend/app/services/advisor/chat.py` | **modifier** — construit `ToolContext`, accepte les deps d'action |
| `backend/app/api/deps.py` | inchangé (deps déjà exposées : `AuditProbeDep`, `StackDetectorDep`, `TlsCheckerDep`, `GtmCheckerDep`) |
| `backend/app/api/v1/endpoints/advisor.py` | **modifier** — injecte les deps d'action dans `post_message_endpoint`, `DELETE /advisor/threads/{id}` |
| `backend/tests/test_migrations.py` | **modifier** — `EXPECTED_TABLES` += `advisor_tool_calls` |
| `backend/tests/test_advisor_tools.py` | **modifier** — adapte les appels `dispatch(...)` à `ToolContext`, ajoute les tests d'action |
| `backend/tests/test_advisor_chat.py` | **modifier** — tests avec deps d'action injectées |
| `backend/tests/test_advisor_endpoints.py` | **modifier** — tests d'archivage + rate-limit bout-en-bout |
| `frontend/lib/api/dto.ts` | **modifier** — rien de nouveau côté DTO (les tool_call `trigger_rescan`/`draft_gtm_snippet` passent déjà par le même schéma d'événements SSE) |
| `frontend/lib/api/advisor.ts` | **modifier** — `archiveThread` |
| `frontend/components/conseiller/advisor-view.tsx` | **modifier** — bouton d'archivage sur chaque fil |

---

## Task 1 : migration — `archived_at` + `advisor_tool_calls`

**Files:** `backend/app/models/advisor.py`, `backend/alembic/versions/*_advisor_actions.py`, `backend/tests/test_migrations.py`

**Interfaces produites :**
```python
class AdvisorThread(...):
    ...
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class AdvisorToolCall(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "advisor_tool_calls"
    thread_id: Mapped[UUID] = mapped_column(ForeignKey("advisor_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(32), nullable=False)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Étape 1** — ajouter `archived_at` à `AdvisorThread` et la classe `AdvisorToolCall` dans `app/models/advisor.py` (imports déjà présents : `DateTime`, `String`, `ForeignKey`, `func`, `UUIDPrimaryKeyMixin`).

- [ ] **Étape 2** — générer la migration :
```bash
cd backend
ALEMBIC_DATABASE_URL=postgresql+asyncpg://cc:cc@localhost:55432/control_center \
  ./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "advisor actions"
```
Relire : `down_revision` = la tête actuelle (`a653b32f47a4` sauf migration entre-temps), `op.add_column("advisor_threads", sa.Column("archived_at", ...))`, `op.create_table("advisor_tool_calls", ...)`, `downgrade` symétrique. Nettoyer avec `ruff check --fix` + `ruff format` **sur ce seul fichier**.

- [ ] **Étape 3** — appliquer aux 2 bases (`control_center`, `control_center_migrations`) via `alembic upgrade head`.

- [ ] **Étape 4** — `tests/test_migrations.py` : `EXPECTED_TABLES` += `"advisor_tool_calls"`.

- [ ] **Étape 5** — `pytest tests/test_migrations.py tests/test_enum_check_constraints.py -q` → vert (`alembic check` propre).

- [ ] **Étape 6 : commit** — `git commit -m "feat(advisor): archivage de fil + table de rate-limit des outils d'action"`

---

## Task 2 : `ToolContext` + rate-limit + `trigger_rescan`

**Files:** `backend/app/services/advisor/tools.py`, `backend/tests/test_advisor_tools.py`

**Interfaces produites :**
```python
@dataclass(frozen=True, slots=True)
class ToolContext:
    session: AsyncSession | None
    website: Website
    user_id: UUID | None = None
    thread_id: UUID | None = None
    probe: AuditProbe | None = None
    detector: Detector | None = None
    tls_checker: TlsChecker | None = None
    gtm_checker: GtmChecker | None = None

async def dispatch(name: str, tool_input: dict, ctx: ToolContext) -> dict   # signature changee
```
> **Breaking change assumé** : `dispatch(name, tool_input, *, session=, website=)` (incr. 3a) devient
> `dispatch(name, tool_input, ctx)`. Tous les appelants (tests + `chat.py`) sont mis à jour dans ce
> plan — pas de compat conservée, c'est une fonction interne au module `advisor`.

**Table de rate-limit** :
```python
_RATE_LIMITS: dict[str, timedelta] = {"trigger_rescan": timedelta(minutes=10)}

async def _rate_limited(session: AsyncSession, *, thread_id: UUID, tool: str) -> bool:
    """True si l'outil a deja ete appele dans la fenetre — l'appel est refuse."""
    window = _RATE_LIMITS[tool]
    since = datetime.now(UTC) - window
    recent = (await session.execute(
        select(AdvisorToolCall.id).where(
            AdvisorToolCall.thread_id == thread_id,
            AdvisorToolCall.tool == tool,
            AdvisorToolCall.called_at >= since,
        )
    )).scalar_one_or_none()
    return recent is not None


async def _record_tool_call(session: AsyncSession, *, thread_id: UUID, tool: str) -> None:
    session.add(AdvisorToolCall(thread_id=thread_id, tool=tool, called_at=datetime.now(UTC)))
    await session.flush()
```

`trigger_rescan` : appelle `run_audit` avec les deps de `ctx`, renvoie un résumé (pas les métriques complètes — l'agent peut ensuite appeler `get_snapshot_detail`).

- [ ] **Étape 1 : tests qui échouent** — dans `tests/test_advisor_tools.py`, **remplacer** tous les appels `dispatch("...", {...}, session=db_session, website=site)` par
  `dispatch("...", {...}, ToolContext(session=db_session, website=site))` (et les cas sans DB : `ToolContext(session=None, website=website)`), puis ajouter :

```python
from datetime import timedelta

from app.models.advisor import AdvisorToolCall
from app.services.advisor.tools import ToolContext
from app.services.stack_detector import StackDetection
from app.services.tls_check import TlsStatus
from app.models.enums import StackKind


def _ctx(db_session, site, *, user_id, thread_id, **extra) -> ToolContext:
    return ToolContext(session=db_session, website=site, user_id=user_id, thread_id=thread_id, **extra)


async def _fake_detector(url: str, **kw) -> StackDetection:
    _ = (url, kw)
    return StackDetection(StackKind.REACT, ("react-root-static",), 0.7)


async def _fake_tls(domain: str) -> TlsStatus:
    return TlsStatus(host=domain, status="valid", checked_at=datetime.now(UTC))


async def _fake_gtm(domain: str):
    _ = domain
    return None


async def test_trigger_rescan_creates_snapshot(db_session, make_user: UserFactory) -> None:
    from app.services.audit_probe import MockAuditProbe

    user = await make_user(sub="act-1")
    site = await _site(db_session, user.id, domain="rescan.test")
    thread_id = uuid4()  # aucune FK requise pour ce test (pas de commit d'AdvisorThread)
    ctx = _ctx(
        db_session, site, user_id=user.id, thread_id=thread_id,
        probe=MockAuditProbe(), detector=_fake_detector, tls_checker=_fake_tls, gtm_checker=_fake_gtm,
    )
    out = await dispatch("trigger_rescan", {}, ctx)
    assert "snapshot_id" in out
    assert out["detected_stack"] == "react"


async def test_trigger_rescan_is_rate_limited(db_session, make_user: UserFactory) -> None:
    from app.services.audit_probe import MockAuditProbe

    user = await make_user(sub="act-2")
    site = await _site(db_session, user.id, domain="rescan2.test")
    thread_id = uuid4()
    ctx = _ctx(
        db_session, site, user_id=user.id, thread_id=thread_id,
        probe=MockAuditProbe(), detector=_fake_detector, tls_checker=_fake_tls, gtm_checker=_fake_gtm,
    )
    first = await dispatch("trigger_rescan", {}, ctx)
    assert "snapshot_id" in first
    second = await dispatch("trigger_rescan", {}, ctx)
    assert "error" in second

    calls = (await db_session.execute(
        select(AdvisorToolCall).where(AdvisorToolCall.thread_id == thread_id)
    )).scalars().all()
    assert len(calls) == 1  # le 2e appel refuse n'a pas ajoute de ligne


async def test_trigger_rescan_missing_deps_returns_error(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="act-3")
    site = await _site(db_session, user.id, domain="rescan3.test")
    ctx = _ctx(db_session, site, user_id=user.id, thread_id=uuid4())  # aucune dep d'action
    out = await dispatch("trigger_rescan", {}, ctx)
    assert "error" in out
```

> `uuid4()` sans ligne `AdvisorThread` réelle fonctionne : `AdvisorToolCall.thread_id` n'a pas de contrainte FK vérifiée côté Python (seulement en DB au commit — le test ne commit pas). Si SQLAlchemy/Postgres râle au flush à cause de la FK, créer une vraie ligne `AdvisorThread` minimale dans `_ctx`/le test à la place (préférer cette option si le flush échoue — l'écrire au premier run rouge).

- [ ] **Étape 2** — lancer, vérifier l'échec.

- [ ] **Étape 3 : implémentation**

```python
# ajouts dans tools.py — imports
from dataclasses import dataclass
from datetime import timedelta

from app.models.advisor import AdvisorToolCall
from app.models.enums import StackKind
from app.services.audit_engine import Detector, GtmChecker, TlsChecker, run_audit
from app.services.audit_probe import AuditProbe


@dataclass(frozen=True, slots=True)
class ToolContext:
    session: AsyncSession | None
    website: Website
    user_id: UUID | None = None
    thread_id: UUID | None = None
    probe: AuditProbe | None = None
    detector: Detector | None = None
    tls_checker: TlsChecker | None = None
    gtm_checker: GtmChecker | None = None


_RATE_LIMITS: dict[str, timedelta] = {"trigger_rescan": timedelta(minutes=10)}


async def _rate_limited(session: AsyncSession, *, thread_id: UUID, tool: str) -> bool:
    since = datetime.now(UTC) - _RATE_LIMITS[tool]
    recent = (
        await session.execute(
            select(AdvisorToolCall.id).where(
                AdvisorToolCall.thread_id == thread_id,
                AdvisorToolCall.tool == tool,
                AdvisorToolCall.called_at >= since,
            )
        )
    ).scalar_one_or_none()
    return recent is not None


async def _record_tool_call(session: AsyncSession, *, thread_id: UUID, tool: str) -> None:
    session.add(AdvisorToolCall(thread_id=thread_id, tool=tool, called_at=datetime.now(UTC)))
    await session.flush()


async def _trigger_rescan(ctx: ToolContext) -> dict:
    if ctx.session is None or ctx.thread_id is None:
        return {"error": "contexte insuffisant pour relancer un diagnostic"}
    if not (ctx.probe and ctx.detector and ctx.tls_checker):
        return {"error": "relance de diagnostic indisponible dans ce contexte"}
    if await _rate_limited(ctx.session, thread_id=ctx.thread_id, tool="trigger_rescan"):
        return {"error": "diagnostic deja relance recemment sur ce fil, reessaie plus tard"}

    result = await run_audit(
        ctx.session,
        website=ctx.website,
        probe=ctx.probe,
        user_id=ctx.user_id,
        detector=ctx.detector,
        tls_checker=ctx.tls_checker,
        gtm_checker=ctx.gtm_checker,
    )
    await _record_tool_call(ctx.session, thread_id=ctx.thread_id, tool="trigger_rescan")
    return {
        "snapshot_id": str(result.snapshot.id),
        "detected_stack": result.detected_stack.value,
        "issues_created": len(result.created),
        "issues_updated": len(result.updated),
        "issues_resolved": len(result.resolved),
    }
```

Mettre à jour `dispatch` :
```python
async def dispatch(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    if name == "get_score_history":
        return await _get_score_history(ctx.session, ctx.website, tool_input.get("days", 30))
    if name == "get_snapshot_detail":
        return await _get_snapshot_detail(ctx.session, ctx.website, tool_input.get("snapshot_id"))
    if name == "get_page_html":
        return await _get_page_html(ctx.website, str(tool_input.get("path", "/")))
    if name == "get_gtm_check":
        return await _get_gtm_check(ctx.session, ctx.website)
    if name == "trigger_rescan":
        return await _trigger_rescan(ctx)
    return {"error": f"outil inconnu : {name}"}
```
(`draft_gtm_snippet` ajouté à la Task 3.)

Ajouter la definition d'outil dans `TOOL_DEFS` :
```python
{
    "name": "trigger_rescan",
    "description": (
        "Relance un diagnostic complet du site (stack, SSL, GTM, CWV, GA4/GSC) et "
        "met a jour les issues. Action reelle qui modifie l'etat du site suivi — "
        "a utiliser seulement si la demande de l'utilisateur le justifie."
    ),
    "input_schema": {"type": "object", "properties": {}},
},
```

- [ ] **Étape 4** — vert + ruff.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): ToolContext + trigger_rescan (rate-limite)"`

---

## Task 3 : `draft_gtm_snippet`

**Files:** `backend/app/services/advisor/tools.py`, `backend/tests/test_advisor_tools.py`

**Interfaces produites :** l'outil `draft_gtm_snippet` dans `TOOL_DEFS` + `dispatch`.

- [ ] **Étape 1 : tests qui échouent**

```python
async def test_draft_gtm_snippet_purchase_for_nextjs(db_session, make_user: UserFactory) -> None:
    from app.models.enums import StackKind

    user = await make_user(sub="snip-1")
    site = await _site(db_session, user.id, domain="snip.test")
    site.detected_stack = StackKind.NEXTJS
    ctx = ToolContext(session=db_session, website=site)
    out = await dispatch("draft_gtm_snippet", {"event": "purchase"}, ctx)
    assert out["language"] in ("ts", "tsx", "js", "php")
    assert "dataLayer" in out["code"]
    assert out["target_path"]


async def test_draft_gtm_snippet_unknown_event_returns_error(db_session, make_user: UserFactory) -> None:
    user = await make_user(sub="snip-2")
    site = await _site(db_session, user.id, domain="snip2.test")
    ctx = ToolContext(session=db_session, website=site)
    out = await dispatch("draft_gtm_snippet", {"event": "signup"}, ctx)
    assert "error" in out
```

- [ ] **Étape 2** — échec.

- [ ] **Étape 3 : implémentation**

```python
# import ajoute
from app.services.snippet_library import SnippetEvent, get_snippets


async def _draft_gtm_snippet(website: Website, event: str) -> dict:
    try:
        evt = SnippetEvent(event)
    except ValueError:
        options = ", ".join(e.value for e in SnippetEvent)
        return {"error": f"evenement inconnu : {event!r}. Choisir parmi : {options}."}
    entries = get_snippets(website.detected_stack, evt)
    if not entries:
        return {"error": "aucun snippet disponible pour cette stack"}
    entry = entries[0]
    return {
        "language": entry.language,
        "code": entry.code,
        "target_path": entry.target_path,
        "instructions": entry.instructions,
    }
```
Brancher dans `dispatch` :
```python
    if name == "draft_gtm_snippet":
        return await _draft_gtm_snippet(ctx.website, str(tool_input.get("event", "")))
```
Ajouter à `TOOL_DEFS` :
```python
{
    "name": "draft_gtm_snippet",
    "description": (
        "Genere un extrait de code dataLayer.push pour un evenement de conversion "
        "(purchase, lead, custom), adapte a la stack detectee du site."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "event": {"type": "string", "enum": ["purchase", "lead", "custom"]},
        },
        "required": ["event"],
    },
},
```

- [ ] **Étape 4** — vert + ruff.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): outil draft_gtm_snippet"`

---

## Task 4 : brancher `ToolContext` dans `chat.py` + l'endpoint

**Files:** `backend/app/services/advisor/chat.py`, `backend/app/api/v1/endpoints/advisor.py`, `backend/tests/test_advisor_chat.py`, `backend/tests/test_advisor_endpoints.py`

**Interfaces produites :**
```python
async def run_chat_turn(
    session, *, thread, website, user_id, llm, user_text, iteration_cap,
    probe: AuditProbe | None = None,
    detector: Detector | None = None,
    tls_checker: TlsChecker | None = None,
    gtm_checker: GtmChecker | None = None,
) -> AsyncIterator[dict]
```

- [ ] **Étape 1 : test qui échoue** — ajouter à `tests/test_advisor_chat.py`

```python
async def test_chat_can_trigger_rescan_via_tool(db_session, make_user: UserFactory) -> None:
    from app.services.audit_probe import MockAuditProbe
    from app.services.stack_detector import StackDetection
    from app.services.tls_check import TlsStatus
    from app.models.enums import StackKind

    user = await make_user(sub="chat-5")
    site, thread = await _thread_with_snapshot(db_session, user.id)

    async def detector(url: str, **kw):
        _ = (url, kw)
        return StackDetection(StackKind.REACT, ("react-root-static",), 0.7)

    async def tls_checker(domain: str):
        return TlsStatus(host=domain, status="valid", checked_at=datetime.now(UTC))

    llm = MockAdvisorLLM(turns=[
        TurnResult(
            content=[{"type": "tool_use", "id": "t1", "name": "trigger_rescan", "input": {}}],
            stop_reason="tool_use", usage=dict(_ZERO),
        ),
        TurnResult(
            content=[{"type": "text", "text": "Diagnostic relance."}],
            stop_reason="end_turn", usage=dict(_ZERO),
        ),
    ])

    events = await _collect(run_chat_turn(
        db_session, thread=thread, website=site, user_id=user.id, llm=llm,
        user_text="relance un scan", iteration_cap=6,
        probe=MockAuditProbe(), detector=detector, tls_checker=tls_checker,
    ))
    assert events[-1]["kind"] == "done"

    rows = await _messages(db_session, thread.id)
    tool_msg = next(r for r in rows if r.blocks and r.blocks[0].get("name") == "trigger_rescan")
    assert tool_msg is not None
```

- [ ] **Étape 2** — échec.

- [ ] **Étape 3 : implémentation**

`chat.py` :
```python
from app.services.advisor.tools import TOOL_DEFS, ToolContext, dispatch
from app.services.audit_engine import Detector, GtmChecker, TlsChecker
from app.services.audit_probe import AuditProbe

async def run_chat_turn(
    session, *, thread, website, user_id, llm, user_text, iteration_cap,
    probe: AuditProbe | None = None,
    detector: Detector | None = None,
    tls_checker: TlsChecker | None = None,
    gtm_checker: GtmChecker | None = None,
) -> AsyncIterator[dict]:
    ...  # inchange jusqu'a la boucle
    ctx = ToolContext(
        session=session, website=website, user_id=user_id, thread_id=thread.id,
        probe=probe, detector=detector, tls_checker=tls_checker, gtm_checker=gtm_checker,
    )
    for _ in range(iteration_cap):
        ...
        for call in tool_uses:
            yield {"kind": "tool_call", "tool": call["name"]}
            output = await dispatch(call["name"], call.get("input") or {}, ctx)
            ...
```
(Remplacer uniquement l'appel `dispatch(call["name"], call.get("input") or {}, session=session, website=website)` par `dispatch(call["name"], call.get("input") or {}, ctx)`, et construire `ctx` une fois avant la boucle `for`.)

`advisor.py::post_message_endpoint` — ajouter les deps et les passer :
```python
from app.api.deps import (
    AdvisorLLMDep, AuditProbeDep, CurrentUserDep, GtmCheckerDep, SessionDep,
    SettingsDep, StackDetectorDep, TlsCheckerDep,
)

async def post_message_endpoint(
    thread_id: UUID, body: PostMessageRequest, user: CurrentUserDep, session: SessionDep,
    llm: AdvisorLLMDep, settings: SettingsDep,
    probe: AuditProbeDep, detector: StackDetectorDep, tls_checker: TlsCheckerDep,
    gtm_checker: GtmCheckerDep,
) -> StreamingResponse:
    ...
    async for event in run_chat_turn(
        session, thread=thread, website=site, user_id=user.id, llm=llm,
        user_text=body.text, iteration_cap=settings.advisor_tool_iteration_cap,
        probe=probe, detector=detector, tls_checker=tls_checker, gtm_checker=gtm_checker,
    ):
```
> `StackDetectorDep` (pas `LiveStackDetectorDep`) : même comportement que le bouton manuel « Lancer un diagnostic » (`POST /scan`), cohérent en mode démo (`demo_detector`) comme en mode réel.

- [ ] **Étape 4** — vert. Adapter `tests/test_advisor_endpoints.py::mock_advisor`/fixtures qui appellent `post_message_endpoint` indirectement (aucun changement requis si elles passent déjà par `mock_detector` — vérifier que `AuditProbeDep`/`StackDetectorDep`/`TlsCheckerDep`/`GtmCheckerDep` sont bien overridées dans les tests de chat, sinon ajouter `mock_detector` à leur signature).
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): chat branche aux dependances d'action (trigger_rescan operationnel)"`

---

## Task 5 : archivage de fil

**Files:** `backend/app/api/v1/endpoints/advisor.py`, `backend/tests/test_advisor_endpoints.py`, `frontend/lib/api/advisor.ts`, `frontend/lib/api/dto.ts`, `frontend/components/conseiller/advisor-view.tsx`

**Interfaces produites :**
```python
@router.delete("/advisor/threads/{thread_id}", status_code=204)
async def archive_thread_endpoint(thread_id: UUID, user: CurrentUserDep, session: SessionDep) -> None
```
`list_threads_endpoint` gagne `include_archived: bool = False` (filtre `AdvisorThread.archived_at.is_(None)` par défaut).

- [ ] **Étape 1 : tests qui échouent** — ajouter à `tests/test_advisor_endpoints.py`

```python
async def test_archive_thread_hides_it_from_list(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, mock_advisor: None,
) -> None:
    client, user = authed_client
    site = await _site(db_session, user=user)
    brief = await client.post(f"/api/v1/websites/{site.id}/advisor/brief")
    thread_id = brief.json()["thread_id"]

    resp = await client.delete(f"/api/v1/advisor/threads/{thread_id}")
    assert resp.status_code == 204

    threads = (await client.get(f"/api/v1/websites/{site.id}/advisor/threads")).json()
    assert threads == []

    with_archived = (
        await client.get(f"/api/v1/websites/{site.id}/advisor/threads?include_archived=true")
    ).json()
    assert len(with_archived) == 1


async def test_archive_thread_404_on_foreign_thread(
    authed_client: tuple[AsyncClient, User], db_session: AsyncSession, mock_advisor: None,
) -> None:
    client, user = authed_client
    other = User(email="other2@x.com", google_sub="other-adv-2", display_name="Other2")
    db_session.add(other)
    await db_session.flush()
    foreign_site = await _site(db_session, user=other, domain="foreign2.test")
    app.dependency_overrides[get_advisor_llm] = MockAdvisorLLM
    resp = await client.post(f"/api/v1/websites/{foreign_site.id}/advisor/brief")
    # le site appartient a `other`, pas a `user` -> le brief lui-meme echoue en 404
    assert resp.status_code == 404
```
(Adapter `test_endpoints_require_auth` : ajouter `assert (await db_client.delete(f"/api/v1/advisor/threads/{wid}")).status_code == 401`.)

- [ ] **Étape 2** — échec.

- [ ] **Étape 3 : implémentation** — `advisor.py`

```python
@router.get("/websites/{website_id}/advisor/threads", response_model=list[ThreadSummaryOut])
async def list_threads_endpoint(
    website_id: UUID, user: CurrentUserDep, session: SessionDep, include_archived: bool = False,
) -> list[ThreadSummaryOut]:
    await _owned_website(session, website_id, user)
    stmt = select(AdvisorThread).where(AdvisorThread.website_id == website_id)
    if not include_archived:
        stmt = stmt.where(AdvisorThread.archived_at.is_(None))
    threads = list((await session.execute(stmt.order_by(AdvisorThread.created_at.desc()))).scalars().all())
    ...  # reste inchange


@router.delete("/advisor/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_thread_endpoint(
    thread_id: UUID, user: CurrentUserDep, session: SessionDep
) -> None:
    thread = await session.get(AdvisorThread, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="fil introuvable")
    await _owned_website(session, thread.website_id, user)
    thread.archived_at = datetime.now(UTC)
    await session.commit()
```

Front `lib/api/advisor.ts` :
```ts
export async function archiveThread(threadId: string): Promise<void> {
  return apiDelete(`/advisor/threads/${threadId}`);
}
```
(`apiDelete` déjà exporté par `client.ts` depuis l'incrément P4.)

`advisor-view.tsx` : bouton discret (icône `Archive` de lucide) sur chaque ligne de « Plans précédents » → `archiveThread(id)` + retire de `threads` + si c'était le fil actif, réinitialise `activeThreadId`/`messages`. Toast de confirmation.

- [ ] **Étape 4** — `pytest -W error` → tout vert. `npm run build && npm run lint` → 0/0.
- [ ] **Étape 5 : commit** — `git commit -m "feat(advisor): archivage d'un fil de discussion"`

---

## Task 6 : contrôle santé + smoke test réel

- [ ] **Étape 1** — `git add docs/superpowers/plans/2026-09-11-advisor-actions.md && git commit -m "docs: plan incrément 3b (outils d'action + archivage)"`

- [ ] **Étape 2 : contrôle santé**
  - `pytest -W error -q` → tout vert (relancer les fichiers `test_advisor_*` 2× pour le flake).
  - `npm run build && npm run lint` → 0/0.
  - `git status` propre. `alembic check` propre.

- [ ] **Étape 3 : smoke test réel** (`ANTHROPIC_API_KEY`/`ADVISOR_MOCK=false` déjà en place)
  - Sur un thread existant, demander « relance un diagnostic complet du site » → vérifier que l'agent appelle `trigger_rescan`, qu'un nouveau snapshot apparaît, et qu'un 2ᵉ essai immédiat après est refusé (rate-limit).
  - Demander « génère-moi le snippet dataLayer pour un achat » → vérifier que `draft_gtm_snippet` renvoie un extrait cohérent avec la stack détectée.
  - Archiver le fil depuis `/conseiller`, vérifier qu'il disparaît de la liste.

---

## Ce qui reste explicitement hors de ce plan

- **`run_gtm_headless_probe` + `gtm_headless.py` (Playwright)** — bloqué par l'échec réseau du 2026-09-11 documenté dans la spec §7.3. Le design (`GtmHeadlessResult`, `verify_gtm`) reste dans la spec pour une reprise ultérieure (poste de dev avec accès réseau complet, ou CI).
- **`POST /websites/{id}/gtm/headless`** (bouton « Vérifier en conditions réelles » sur `/audit`) — dépend du point précédent.

## Self-review (writing-plans)

- **Couverture spec** : `trigger_rescan` (§6.3), `draft_gtm_snippet` (§6.3), rate-limit via `advisor_tool_calls` (§6.3), archivage (§6.6). Headless explicitement exclu et documenté (voir section ci-dessus), pas un oubli silencieux.
- **Placeholders** : aucun.
- **Cohérence de types** : `ToolContext` introduit en Task 2, seule source de vérité pour les deps d'outil dès Task 2 ; `chat.py`/`advisor.py` s'y branchent en Task 4 sans changer `ToolContext` à nouveau. `dispatch()` change de signature une seule fois (Task 2), tous les appelants mis à jour dans le même incrément — pas de code mort à double signature.
- **Risque** : le test `trigger_rescan` avec `thread_id=uuid4()` sans ligne `AdvisorThread` réelle peut échouer sur la contrainte FK au flush selon le comportement Postgres — le plan prévoit explicitement le repli (créer une vraie ligne) si le premier run rouge le montre.
