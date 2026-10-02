# Durcissement du lot B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger six défauts connus du lot B (PR #19) avant d'activer le planificateur en production : perte de données CrUX, mauvaise classification des 403 de quota, 409 Cloud Tasks trop laxiste, effet de troupeau des créneaux quotidiens, liste blanche OIDC globale, Chromium/worker lancé sans décision explicite.

**Architecture:** Six correctifs indépendants sur du code existant. Aucune table, aucune route publique, aucune migration. Tout changement de comportement est rétrocompatible par défaut (variable absente = comportement actuel).

**Tech Stack:** FastAPI, SQLAlchemy async, httpx, pytest-asyncio, Playwright.

**Spec:** pas de spec séparée — constats de la revue finale du lot B (mémoire `roadmap-v3-and-production-foundation`) confirmés par lecture du code (fichiers et fonctions cités par tâche). Deux points de la liste d'origine sont écartés après vérification : la pagination Search Console est déjà faite (`GscSource._query`, `_MAX_PAGES`), et la vérification OIDC est déjà 100 % JWKS local (pas de repli « tokeninfo » à retirer).

## Global Constraints

- La suite existante reste verte : `cd backend && uv run pytest -W error -q` (nécessite la base de test habituelle du dépôt) et `uv run ruff check .`.
- Aucune migration, aucun changement de schéma.
- Aucun secret, jeton, URL de client ni corps de réponse Google dans un message de log ou d'exception (convention du dépôt : seuls des codes connus sont comparés ou journalisés).
- Rétrocompatibilité : une nouvelle variable d'environnement absente ou vide reproduit le comportement actuel.
- Commits en français, impératif court, style de `git log`. Une tâche = un commit au minimum.
- TDD : test qui échoue d'abord, puis le correctif.

---

### Task 1: CrUX — garder les données terrain quand le labo Lighthouse échoue

**Files:**
- Modify: `backend/app/services/metrics/sources/cwv.py` (`parse_cwv`, lignes 85-120)
- Test: `backend/tests/test_metrics_sources_cwv_probes.py`

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: `parse_cwv(payload, *, day) -> list[Observation]`, signature inchangée.

Contexte : aujourd'hui un `lighthouseResult.runtimeError.code` autre que `NO_ERROR` lève `SourceError("site_unreachable")` AVANT de lire `originLoadingExperience`, qui est une mesure Google indépendante (28 jours de vrais visiteurs). Une page anti-robot fait donc perdre des données terrain valides.

- [ ] **Step 1: Écrire les tests qui échouent** (à ajouter après `test_parse_cwv_runtime_error_no_error_is_not_a_failure`)

```python
def test_parse_cwv_runtime_error_keeps_valid_field_data() -> None:
    # Le labo peut échouer (anti-robot, délai dépassé) alors que les données terrain
    # CrUX, calculées par Google sur 28 jours, restent valides : les jeter est une perte.
    payload = {
        "lighthouseResult": {"runtimeError": {"code": "PROTOCOL_TIMEOUT", "message": "x"}},
        "originLoadingExperience": {"metrics": _ORIGIN},
    }
    observations = parse_cwv(payload, day=TODAY)
    assert {o.metric: o.value for o in observations} == {
        "lcp_p75_ms": 2300.0,
        "inp_p75_ms": 180.0,
        "cls_p75": 0.05,
    }


def test_parse_cwv_runtime_error_never_reads_the_lab_score() -> None:
    payload = {
        "lighthouseResult": {
            "runtimeError": {"code": "NO_FCP", "message": "x"},
            "categories": {"performance": {"score": 0.9}},
        },
        "originLoadingExperience": {"metrics": _ORIGIN},
    }
    metrics = {o.metric for o in parse_cwv(payload, day=TODAY)}
    assert "performance_score" not in metrics and "lcp_p75_ms" in metrics
```

Le test existant `test_parse_cwv_a_lighthouse_runtime_error_is_site_unreachable` (payload sans `originLoadingExperience`) doit continuer à passer sans modification.

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd backend && uv run pytest tests/test_metrics_sources_cwv_probes.py -k runtime_error -q`
Expected: les 2 nouveaux tests FAIL (`SourceError site_unreachable`).

- [ ] **Step 3: Implémenter** — remplacer le corps de `parse_cwv` à partir de `runtime_error = ...` par :

```python
    lab_failed = False
    runtime_error = lighthouse.get("runtimeError")
    if runtime_error is not None:
        if not isinstance(runtime_error, dict):
            raise _bad_shape()
        code = runtime_error.get("code")
        if isinstance(code, str) and code and code != "NO_ERROR":
            # Lighthouse dit ne pas avoir pu mesurer la page (ex. NO_FCP, PROTOCOL_TIMEOUT).
            # Cela n'invalide que le score de laboratoire : `originLoadingExperience` est
            # une mesure Google indépendante (vrais visiteurs, fenêtre de 28 jours).
            lab_failed = True
    metrics = _section(_section(payload, "originLoadingExperience"), "metrics")
    observations: list[Observation] = []
    for name, keys in _FIELD_METRICS.items():
        percentile = _percentile(metrics, *keys)
        if percentile is None:
            continue
        # CrUX donne le CLS multiplié par 100.
        value = percentile / 100 if name == "cls_p75" else percentile
        observations.append(Observation(name, day, value))
    if lab_failed:
        if not observations:
            # Labo en échec ET aucune donnée terrain : rien d'exploitable ce jour-là, un
            # `[]` passerait pour un succès.
            raise SourceError("site_unreachable", recoverable=False)
        return observations
    performance = _section(_section(lighthouse, "categories"), "performance")
    # `score: null` est la réponse de Lighthouse quand la mesure a échoué : pas de donnée.
    score = performance.get("score")
    if score is not None:
        number = _finite_number(score)
        if number is None or not 0 <= number <= 1:
            raise _bad_shape()
        observations.append(Observation("performance_score", day, round(number * 100, 1)))
    return observations
```

- [ ] **Step 3bis: Mettre à jour la docstring du module** : ajouter à la fin du paragraphe d'en-tête « Un échec du laboratoire (`runtimeError`) n'invalide que le score Lighthouse : les données terrain valides sont gardées. »

- [ ] **Step 4: Lancer le fichier de tests complet**

Run: `cd backend && uv run pytest tests/test_metrics_sources_cwv_probes.py -q`
Expected: tout PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/metrics/sources/cwv.py backend/tests/test_metrics_sources_cwv_probes.py
git commit -m "fix(cwv): garder les donnees terrain CrUX quand le labo Lighthouse echoue"
```

---

### Task 2: 403 de quota Google classés « quota », pas « droits refusés »

**Files:**
- Modify: `backend/app/services/measurement/google_reader.py` (`_raise_for_status`, lignes 93-105)
- Test: `backend/tests/test_measurement_google_reader.py`

**Interfaces:**
- Consumes: rien.
- Produces: `_raise_for_status(response)` lève `GoogleReadError("quota")` pour un 403 dont le corps porte une raison de quota ; sinon inchangé. Les consommateurs (`google_http.py` `RECOVERABLE_REASONS["quota"] = True`, `jobs/handlers.py` disjoncteur, `jobs/messages.py`, `jobs/health.py` `CLIENT_ACTION_CODES`) gèrent déjà `quota` : aucun changement requis chez eux.

Contexte : Google répond parfois 403 (pas 429) quand le quota est épuisé. Aujourd'hui tout 403 devient `permission_or_api_disabled` : non récupérable, affiché au client comme « reconnecte ton compte », et le disjoncteur de quota ne se déclenche jamais.

- [ ] **Step 1: Écrire les tests qui échouent** (à ajouter après `test_http_errors_map_to_reasons`)

```python
@pytest.mark.parametrize(
    "body",
    [
        {"error": {"code": 403, "status": "RESOURCE_EXHAUSTED", "message": "x"}},
        {"error": {"code": 403, "errors": [{"reason": "rateLimitExceeded"}]}},
        {"error": {"code": 403, "errors": [{"reason": "dailyLimitExceeded"}]}},
        {"error": {"code": 403, "details": [{"reason": "quotaExceeded"}]}},
        {"error": {"code": 403, "errors": [{"reason": "userRateLimitExceeded"}]}},
    ],
)
async def test_a_403_with_a_quota_reason_is_a_quota_error(body: dict) -> None:
    reader = _reader(lambda request: httpx.Response(403, json=body))
    with pytest.raises(GoogleReadError) as excinfo:
        await reader.event_stats()
    assert excinfo.value.reason == "quota"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"error": {"code": 403, "status": "PERMISSION_DENIED"}},
        {"error": {"code": 403, "errors": [{"reason": "forbidden"}]}},
        {"error": "pas un objet"},
        {"error": {"errors": "pas une liste"}},
    ],
)
async def test_a_403_without_a_quota_reason_stays_a_permission_error(body: dict) -> None:
    reader = _reader(lambda request: httpx.Response(403, json=body))
    with pytest.raises(GoogleReadError) as excinfo:
        await reader.event_stats()
    assert excinfo.value.reason == "permission_or_api_disabled"


async def test_a_non_json_403_stays_a_permission_error() -> None:
    reader = _reader(lambda request: httpx.Response(403, content=b"<html>Forbidden</html>"))
    with pytest.raises(GoogleReadError) as excinfo:
        await reader.event_stats()
    assert excinfo.value.reason == "permission_or_api_disabled"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_measurement_google_reader.py -k "403" -q`
Expected: `test_a_403_with_a_quota_reason_is_a_quota_error` FAIL, les autres PASS.

- [ ] **Step 3: Implémenter** — dans `google_reader.py`, juste avant `_raise_for_status` :

```python
# Raisons Google d'un quota épuisé, parfois servies avec un 403 plutôt qu'un 429.
_QUOTA_REASONS = frozenset(
    {
        "RESOURCE_EXHAUSTED",
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "dailyLimitExceeded",
        "quotaExceeded",
    }
)


def _error_reasons(response: httpx.Response) -> set[str]:
    """Codes de raison du corps d'erreur Google (`error.status`, `error.errors[].reason`,
    `error.details[].reason`). Jamais le message, qui peut citer une ressource."""
    try:
        body = response.json()
    except ValueError:
        return set()
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return set()
    reasons: set[str] = set()
    status = error.get("status")
    if isinstance(status, str):
        reasons.add(status)
    for list_key in ("errors", "details"):
        items = error.get(list_key)
        for item in items if isinstance(items, list) else []:
            reason = item.get("reason") if isinstance(item, dict) else None
            if isinstance(reason, str):
                reasons.add(reason)
    return reasons
```

et dans `_raise_for_status`, remplacer la branche 403 par :

```python
    if code == 403:
        # Un quota épuisé et un refus de droits n'appellent pas la même réaction : l'un
        # se résout seul (nouvel essai, disjoncteur), l'autre demande une action du client.
        if _error_reasons(response) & _QUOTA_REASONS:
            raise GoogleReadError("quota")
        raise GoogleReadError("permission_or_api_disabled")
```

- [ ] **Step 3bis: Test de bout en bout du côté lot B** — ajouter dans `backend/tests/` (fichier existant des sources GA4/GSC ou de `google_json`, à repérer avec `grep -rn google_json backend/tests`) un test : `google_json` sur un 403 `rateLimitExceeded` lève `SourceError(reason="quota", recoverable=True)` ; sur un 403 vide, `SourceError("permission_or_api_disabled", recoverable=False)`.

- [ ] **Step 4: Suite concernée**

Run: `cd backend && uv run pytest tests/test_measurement_google_reader.py tests/test_jobs_handlers.py -q` (et le fichier du Step 3bis)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/measurement/google_reader.py backend/tests
git commit -m "fix(google): un 403 de quota est classe quota, pas droits refuses"
```

---

### Task 3: Cloud Tasks — n'ignorer le 409 que s'il dit ALREADY_EXISTS

**Files:**
- Modify: `backend/app/services/jobs/cloud_tasks.py` (`CloudTasksQueue.enqueue`, lignes 86-89)
- Test: `backend/tests/test_jobs_cloud_tasks.py`

**Interfaces:**
- Consumes: `EnqueueError(reason)` de `app.services.jobs.queue`.
- Produces: un 409 sans `error.status == "ALREADY_EXISTS"` lève `EnqueueError("http_409")` ; avec ce statut, retour silencieux comme aujourd'hui.

Contexte : tout 409 est aujourd'hui avalé comme « tâche déjà déposée ». Un 409 d'une autre nature (file dans un état conflictuel) ferait perdre la tâche sans trace.

- [ ] **Step 1: Lire `backend/tests/test_jobs_cloud_tasks.py`** pour réutiliser son transport simulé et repérer l'éventuel test 409 existant (il utilise sans doute `httpx.Response(409, ...)` sans corps réaliste : le mettre à jour avec un vrai corps).

- [ ] **Step 2: Écrire les tests qui échouent**

```python
async def test_a_409_already_exists_is_a_silent_duplicate() -> None:
    body = {"error": {"code": 409, "status": "ALREADY_EXISTS", "message": "x"}}
    queue = _queue(lambda request: httpx.Response(409, json=body))  # adapter à l'aide du fichier
    await queue.enqueue(_message())  # ne lève pas


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, json={}),
        httpx.Response(409, json={"error": {"code": 409, "status": "ABORTED"}}),
        httpx.Response(409, content=b"<html>conflict</html>"),
    ],
)
async def test_any_other_409_is_an_enqueue_error(response: httpx.Response) -> None:
    queue = _queue(lambda request: response)
    with pytest.raises(EnqueueError) as excinfo:
        await queue.enqueue(_message())
    assert excinfo.value.reason == "http_409"
```

(`_queue` et `_message` : reprendre les aides déjà présentes dans le fichier ; si elles portent d'autres noms, utiliser ces noms.)

- [ ] **Step 3: Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_jobs_cloud_tasks.py -q`
Expected: les 3 cas « autre 409 » FAIL.

- [ ] **Step 4: Implémenter** — remplacer les lignes 86-89 :

```python
        if response.status_code == 409:
            if _is_already_exists(response):  # déjà déposée : c'est le but de la clé
                return
            raise EnqueueError("http_409")
        if response.status_code >= 400:
            raise EnqueueError(f"http_{response.status_code}")
```

et ajouter au module :

```python
def _is_already_exists(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("status") == "ALREADY_EXISTS"
```

- [ ] **Step 5: Tests du fichier, puis commit**

Run: `cd backend && uv run pytest tests/test_jobs_cloud_tasks.py tests/test_jobs_scheduler.py -q`

```bash
git add backend/app/services/jobs/cloud_tasks.py backend/tests/test_jobs_cloud_tasks.py
git commit -m "fix(jobs): un 409 Cloud Tasks n'est un doublon que s'il dit ALREADY_EXISTS"
```

---

### Task 4: Répartir les créneaux de chaque planning (effet de troupeau)

**Files:**
- Modify: `backend/app/services/jobs/kinds.py` (nouvelle `schedule_offset`, `slot_start` gagne `offset`)
- Modify: `backend/app/services/jobs/scheduler.py` (`tick`, ligne 255)
- Create: `backend/tests/test_jobs_kinds.py`
- Modify: `backend/tests/test_jobs_scheduler.py` (assertions d'échéance exactes, voir Step 5)

**Interfaces:**
- Produces: `schedule_offset(schedule_id: UUID, interval: timedelta) -> timedelta` dans `[0, interval)`, stable pour un identifiant donné ; `slot_start(now, interval, *, offset: timedelta = timedelta(0)) -> datetime`.
- `plan_run` NE CHANGE PAS (étiquette de fenêtre et clé d'idempotence restent alignées sur la grille Unix : « quel jour » et non « à quelle heure »). Seule l'échéance `next_due_at` calculée par `tick` est décalée.

Contexte : `slot_start` aligne tout sur l'époque Unix ; un planning « tous les jours » retombe donc à 00:00 UTC pour TOUS les sites, et leurs collectes Google partent ensemble (quotas). L'échéance de première création est déjà étalée (`now` à la matérialisation) ; c'est le recalage sur la grille après le premier passage qui l'écrase.

**Ruling (à garder dans le code en commentaire court)** : le plafond quotidien d'un workspace (`_next_midnight`) reste à minuit UTC non décalé, car le compteur `runs_today` se remet à zéro à minuit UTC pile. Un planning retenu par ce plafond peut donc, rarement, reprendre son échéance à minuit non décalé : acceptable (plafond de 300 tâches/jour/workspace).

- [ ] **Step 1: Écrire `backend/tests/test_jobs_kinds.py` (échoue : `schedule_offset` n'existe pas)**

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.services.jobs.kinds import schedule_offset, slot_start

A = UUID("11111111-1111-1111-1111-111111111111")
B = UUID("22222222-2222-2222-2222-222222222222")
DAY = timedelta(days=1)


def test_schedule_offset_is_stable_and_within_the_interval() -> None:
    offset = schedule_offset(A, DAY)
    assert timedelta(0) <= offset < DAY
    assert schedule_offset(A, DAY) == offset


def test_schedule_offset_differs_between_schedules() -> None:
    assert schedule_offset(A, DAY) != schedule_offset(B, DAY)


def test_schedule_offset_scales_with_the_interval() -> None:
    eight_hours = timedelta(hours=8)
    assert timedelta(0) <= schedule_offset(A, eight_hours) < eight_hours


def test_slot_start_without_offset_is_the_unix_grid() -> None:
    now = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)
    assert slot_start(now, DAY) == datetime(2026, 9, 26, tzinfo=UTC)


def test_slot_start_with_an_offset_shifts_the_grid() -> None:
    now = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)
    assert slot_start(now, DAY, offset=timedelta(hours=3)) == datetime(2026, 9, 26, 3, tzinfo=UTC)


def test_slot_start_before_the_shifted_boundary_stays_in_the_previous_slot() -> None:
    now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
    assert slot_start(now, DAY, offset=timedelta(hours=3)) == datetime(2026, 9, 25, 3, tzinfo=UTC)
```

Run: `cd backend && uv run pytest tests/test_jobs_kinds.py -q` — Expected: échec d'import.

- [ ] **Step 2: Implémenter dans `kinds.py`** — `import hashlib` en tête, puis remplacer `slot_start` :

```python
def schedule_offset(schedule_id: UUID, interval: timedelta) -> timedelta:
    """Décalage stable de CE planning dans `[0, interval)`.

    Sans lui, tous les plannings « tous les jours » retombent à minuit UTC pile (grille
    Unix) et lancent leurs collectes Google en même temps. Dérivé de l'identifiant du
    planning : deux sources d'un même site se décalent aussi l'une de l'autre."""
    digest = hashlib.sha256(schedule_id.bytes).digest()
    return interval * (int.from_bytes(digest[:8], "big") / 2**64)


def slot_start(now: datetime, interval: timedelta, *, offset: timedelta = timedelta(0)) -> datetime:
    """Début du créneau contenant `now` (grille Unix en UTC décalée de `offset`)."""
    anchor = _EPOCH + offset
    return anchor + ((now - anchor) // interval) * interval
```

- [ ] **Step 3: Tests purs au vert**

Run: `cd backend && uv run pytest tests/test_jobs_kinds.py -q` — Expected: PASS.

- [ ] **Step 4: Brancher dans `scheduler.py`** — importer `schedule_offset` depuis `app.services.jobs.kinds` et remplacer la ligne `next_slot = slot_start(now, interval) + interval` de `tick` par :

```python
            next_slot = slot_start(
                now, interval, offset=schedule_offset(schedule.id, interval)
            ) + interval
```

`plan_run` reste inchangé.

- [ ] **Step 5: Adapter `backend/tests/test_jobs_scheduler.py`** — importer `KINDS`, `effective_interval`, `schedule_offset`, `slot_start` depuis `app.services.jobs.kinds`, ajouter l'aide :

```python
def _own_next_slot(schedule: Schedule, now: datetime = NOW) -> datetime:
    interval = effective_interval(KINDS[schedule.kind], schedule.frequency)
    return slot_start(now, interval, offset=schedule_offset(schedule.id, interval)) + interval
```

Remplacer ensuite, et seulement ceci, les assertions d'échéance CALCULÉE par `tick` (les clés/étiquettes `20260926T0000` ne changent pas ; les échéances restaurées `== NOW` et `== edited` ne changent pas non plus) :
  - `test_a_first_tick_backfills_google_sources_and_runs_the_others` : `schedules["collect_cwv"].next_due_at == _own_next_slot(schedules["collect_cwv"])` et idem `collect_probes`.
  - `test_the_frequency_floor_applies_even_to_a_bad_row` : `schedules["collect_ga4"].next_due_at == _own_next_slot(schedules["collect_ga4"])` (intervalle plancher de 8 h).
  - `test_a_key_already_queued_or_finished_is_not_deposited_again` : idem pour `collect_cwv`.
  - `test_the_workspace_daily_cap_holds_back_extra_tasks` : le choix des 2 plannings déposés dépend de l'ordre des UUID (même `next_due_at`), donc ne plus coder en dur un dictionnaire ; remplacer le bloc `midnight = ...` / `assert {kind: ...} == {...}` par :

```python
    processed = {m.spec.kind for m in site_messages}
    schedules = await _schedules(db_session, site.id)
    midnight = datetime(2026, 9, 27, tzinfo=UTC)
    for kind, schedule in schedules.items():
        own = _own_next_slot(schedule)
        expected = own if kind in processed else min(own, midnight)
        assert schedule.next_due_at == expected, kind
```

  (le `kind` des messages d'un backfill est `backfill` : adapter `processed` pour mapper `backfill` + `params["source"]` vers `collect_<source>`, comme le fait `by_kind` plus haut dans le fichier.)

- [ ] **Step 6: Suite du planificateur et des tâches**

Run: `cd backend && uv run pytest tests/test_jobs_kinds.py tests/test_jobs_scheduler.py tests/test_worker_app.py -q -W error`
Expected: PASS. Si une autre suite échoue sur une échéance exacte, `grep -rn "next_due_at" backend/tests` et appliquer la même règle.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/jobs backend/tests/test_jobs_kinds.py backend/tests/test_jobs_scheduler.py
git commit -m "fix(jobs): decaler l'echeance de chaque planning pour eviter l'effet de troupeau"
```

---

### Task 5: Liste blanche OIDC par route interne

**Files:**
- Modify: `backend/app/config.py` (après `internal_allowed_invokers`, ligne 95)
- Modify: `backend/app/worker_main.py` (`create_worker_app`)
- Modify: `backend/app/api/internal_auth.py`
- Modify: `backend/app/api/internal.py` (décorateurs de `/tick`, `/tasks/run`, `/headless/verify`)
- Modify: `deploy/env.example.yaml`, `docs/ops/runbook.md` (§15)
- Test: `backend/tests/test_worker_app.py`

**Interfaces:**
- Produces: trois réglages `internal_scheduler_invokers`, `internal_tasks_invokers`, `internal_headless_invokers` (`list[str]`, défaut `[]`) ; dépendances FastAPI `require_scheduler_caller`, `require_tasks_caller`, `require_headless_caller` (chacune renvoie `OidcIdentity`).
- Règle : le contrôle global `require_internal_caller` (inchangé, au niveau du routeur) s'exécute toujours ; une liste de route NON VIDE ajoute une restriction. Liste vide = pas de restriction supplémentaire (comportement actuel). `/internal/jobs/health` garde la liste globale seule (route d'exploitation, le runbook y emprunte l'identité du compte Scheduler).
- Correspondance cible (runbook §15.1) : `/internal/tick` ← compte `guiili-scheduler` ; `/internal/tasks/run` ← compte `guiili-tasks` ; `/internal/headless/verify` ← compte d'exécution de l'API.

- [ ] **Step 1: Écrire les tests qui échouent** (à ajouter dans `test_worker_app.py`, qui fournit déjà `worker_app`, `worker`, `_auth`, `CALLER`, `AUDIENCE`)

Le fixture `worker_app` autorise `CALLER` dans la liste globale. Ajouter un second appelant autorisé globalement mais pas par route :

```python
OTHER = "guiili-scheduler@guiili.iam.gserviceaccount.com"


@pytest_asyncio.fixture
async def strict_worker_app(db_session: AsyncSession):
    async def fetch_jwks() -> dict:
        return jwks_for(SIGNING_KEY)

    verifier = OidcVerifier(
        audience=AUDIENCE, allowed_emails={CALLER, OTHER}, fetch_jwks=fetch_jwks
    )
    settings = get_settings().model_copy(
        update={
            "internal_scheduler_invokers": [OTHER],
            "internal_tasks_invokers": [CALLER],
            "internal_headless_invokers": [CALLER],
        }
    )
    application = create_worker_app(settings, oidc_verifier=verifier)

    async def _session():
        yield db_session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_job_services] = lambda: fake_services(_sources())
    application.dependency_overrides[get_headless_runner] = lambda: _fake_headless
    return application


@pytest_asyncio.fixture
async def strict_worker(strict_worker_app):
    async with AsyncClient(
        transport=ASGITransport(app=strict_worker_app), base_url="http://w"
    ) as client:
        yield client


@pytest.mark.parametrize(
    ("method", "path", "body", "allowed", "refused"),
    [
        ("POST", "/internal/tick", None, OTHER, CALLER),
        ("POST", "/internal/tasks/run", {"kind": "partition_maintenance", "window": "20260926"},
         CALLER, OTHER),
    ],
)
async def test_a_route_only_accepts_its_own_invoker(
    strict_worker, method, path, body, allowed, refused
) -> None:
    denied = await strict_worker.request(method, path, json=body, headers=_auth(refused))
    assert denied.status_code == 403
    ok = await strict_worker.request(method, path, json=body, headers=_auth(allowed))
    assert ok.status_code == 200, ok.text


async def test_headless_only_accepts_its_own_invoker(
    strict_worker, db_session: AsyncSession, make_user
) -> None:
    await make_site(db_session, make_user, "strict-headless.test")
    body = {"url": "https://strict-headless.test"}
    denied = await strict_worker.post("/internal/headless/verify", json=body, headers=_auth(OTHER))
    assert denied.status_code == 403
    ok = await strict_worker.post("/internal/headless/verify", json=body, headers=_auth(CALLER))
    assert ok.status_code == 200


async def test_the_health_route_keeps_the_global_allowlist(strict_worker) -> None:
    for email in (CALLER, OTHER):
        assert (await strict_worker.get("/internal/jobs/health", headers=_auth(email))).status_code == 200
    stranger = await strict_worker.get("/internal/jobs/health", headers=_auth("intrus@example.com"))
    assert stranger.status_code == 403


async def test_empty_route_lists_keep_the_current_behaviour(worker) -> None:
    # Le fixture `worker` n'a aucune liste par route : tout appelant global passe partout.
    assert (await worker.post("/internal/tick", headers=_auth())).status_code == 200
```

(`jwks_for`, `SIGNING_KEY`, `fake_services`, `_sources`, `_fake_headless`, `get_job_services`, `get_headless_runner`, `get_session` sont déjà importés dans ce fichier.)

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_worker_app.py -k "invoker or global_allowlist or empty_route" -q`
Expected: FAIL (`internal_scheduler_invokers` inconnu).

- [ ] **Step 3: Réglages** — dans `config.py`, après `internal_allowed_invokers` :

```python
    # Restrictions par route, en plus de la liste globale ci-dessus. Vide = pas de
    # restriction supplémentaire (comportement d'avant). /tick : compte du Scheduler ;
    # /tasks/run : compte de Cloud Tasks ; /headless/verify : compte d'exécution de l'API.
    internal_scheduler_invokers: list[str] = []
    internal_tasks_invokers: list[str] = []
    internal_headless_invokers: list[str] = []
```

- [ ] **Step 4: État de l'application** — dans `create_worker_app`, après `application.state.oidc_verifier = oidc_verifier` :

```python
    application.state.route_invokers = {
        "scheduler": frozenset(e.lower() for e in settings.internal_scheduler_invokers),
        "tasks": frozenset(e.lower() for e in settings.internal_tasks_invokers),
        "headless": frozenset(e.lower() for e in settings.internal_headless_invokers),
    }
```

- [ ] **Step 5: Dépendances** — ajouter à `internal_auth.py` (importer `Annotated`, `Depends`, `Callable`) :

```python
def _route_caller(role: str) -> Callable[..., Awaitable[OidcIdentity]]:
    async def check(
        request: Request, identity: Annotated[OidcIdentity, Depends(require_internal_caller)]
    ) -> OidcIdentity:
        allowed = request.app.state.route_invokers.get(role)
        if allowed and identity.email not in allowed:
            logger.warning(
                "appel interne refusé pour cette route",
                extra={"event": "internal_denied", "reason": "caller_not_allowed_for_route",
                       "route_role": role},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="appelant interne non autorisé"
            )
        return identity

    return check


require_scheduler_caller = _route_caller("scheduler")
require_tasks_caller = _route_caller("tasks")
require_headless_caller = _route_caller("headless")
```

`require_internal_caller` est déjà une dépendance du routeur : FastAPI met son résultat en cache dans la requête, le jeton n'est donc vérifié qu'une fois.

- [ ] **Step 6: Routes** — dans `internal.py`, importer les trois dépendances et ajouter `dependencies=[Depends(require_scheduler_caller)]` à `@router.post("/tick", ...)`, `dependencies=[Depends(require_tasks_caller)]` à `@router.post("/tasks/run", ...)` et `dependencies=[Depends(require_headless_caller)]` à `@router.post("/headless/verify")`. `/jobs/health` reste inchangée.

- [ ] **Step 7: Tests**

Run: `cd backend && uv run pytest tests/test_worker_app.py tests/test_oidc.py tests/test_headless_delegation.py -q -W error`
Expected: PASS (dont `test_internal_routes_require_a_google_identity` et `test_an_app_without_verifier_refuses_every_internal_route`, inchangés).

- [ ] **Step 8: Documentation** — `deploy/env.example.yaml` : ajouter, commentées, `INTERNAL_SCHEDULER_INVOKERS`, `INTERNAL_TASKS_INVOKERS`, `INTERNAL_HEADLESS_INVOKERS` (format liste JSON, comme `INTERNAL_ALLOWED_INVOKERS`) avec la correspondance route → compte. `docs/ops/runbook.md` §15.1 : une phrase décrivant les trois réglages optionnels et le fait qu'ils sont à renseigner après le 1er déploiement stable ; `check_env` (`backend/app/tools/check_env.py`) n'a pas à les exiger.

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/tests/test_worker_app.py deploy/env.example.yaml docs/ops/runbook.md
git commit -m "feat(worker): liste blanche OIDC par route interne (tick, tasks, headless)"
```

---

### Task 6: Chromium du worker — décision explicite et exécution hors root

**Files:**
- Modify: `backend/app/services/gtm_headless.py` (ligne 234, `chromium.launch()`)
- Modify: `backend/Dockerfile.worker`
- Test: `backend/tests/test_gtm_headless.py`

**Interfaces:**
- Produces: `chromium.launch(chromium_sandbox=False)` explicite ; image worker exécutée par un utilisateur non privilégié.

Contexte : `launch()` est appelé sans argument et le conteneur tourne en root. Playwright désactive de lui-même le bac à sable Chromium par défaut (`chromiumSandbox` à faux) : le comportement n'est donc dicté par aucun choix écrit. Sous Cloud Run (gVisor) le bac à sable de Chromium ne peut généralement pas s'initialiser ; la défense réelle est l'isolement du conteneur, du compte de service et du réseau. On rend ce choix explicite et on retire les privilèges root (défense en profondeur), sans tenter d'activer un bac à sable qui échouerait.

**Ruling :** on n'active PAS `chromium_sandbox=True` (échec de lancement probable sous gVisor, non vérifiable ici) ; on documente le choix et on retire root. L'activation du bac à sable reste un suivi à tester directement sur Cloud Run staging.

- [ ] **Step 1: Test qui échoue** — lire `backend/tests/test_gtm_headless.py` pour voir comment `async_playwright` est simulé, puis ajouter un test qui capture les arguments reçus par `pw.chromium.launch` et vérifie `kwargs.get("chromium_sandbox") is False` (ne pas lancer de vrai navigateur).

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `cd backend && uv run pytest tests/test_gtm_headless.py -q`

- [ ] **Step 3: Implémenter** — remplacer `browser = await pw.chromium.launch()` par :

```python
            # Choix explicite : sous Cloud Run (gVisor) le bac à sable propre à Chromium ne
            # s'initialise pas ; l'isolement réel est celui du conteneur (utilisateur non
            # privilégié, Dockerfile.worker), du compte de service et du réseau.
            browser = await pw.chromium.launch(chromium_sandbox=False)
```

- [ ] **Step 4: `Dockerfile.worker`** — la commande d'installation de Chromium doit écrire dans un dossier lisible par l'utilisateur final. Remplacer le bloc `RUN uv run ... playwright install ...` + `ENV PATH` par :

```dockerfile
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Chromium + dependances systeme (fonts, libgtk, libnss...) du rendu headless reel.
RUN uv run --frozen --no-dev playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 guiili \
    && chown -R guiili:guiili /app /ms-playwright

ENV PATH="/app/.venv/bin:${PATH}"

# Chromium ne tourne jamais en root : defense en profondeur (le bac a sable propre a
# Chromium est desactive explicitement, voir app/services/gtm_headless.py).
USER guiili
```

(`EXPOSE` et `CMD` inchangés, après `USER`.)

- [ ] **Step 5: Vérifier l'image si Docker est disponible**

Run: `docker build -f backend/Dockerfile.worker -t guiili-worker-test backend` puis `docker run --rm guiili-worker-test id -u` (attendu : `10001`) et `docker run --rm guiili-worker-test python -c "from playwright.sync_api import sync_playwright as p; b=p().start().chromium.launch(chromium_sandbox=False); print(b.version); b.close()"`.
Si Docker n'est pas disponible dans cet environnement, ne rien inventer : le noter dans le rapport comme NON VÉRIFIÉ ; la vérification se fera au déploiement staging (`/internal/headless/verify` sur un site connu).

- [ ] **Step 6: Tests et commit**

Run: `cd backend && uv run pytest tests/test_gtm_headless.py tests/test_deploy_assets.py -q`
(`test_deploy_assets.py` surveille les actifs de déploiement : s'il vérifie le contenu du Dockerfile, l'adapter.)

```bash
git add backend/app/services/gtm_headless.py backend/Dockerfile.worker backend/tests/test_gtm_headless.py
git commit -m "fix(worker): bac a sable Chromium explicite et image worker hors root"
```
