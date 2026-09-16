# Connexion Google pour les données (GA4/GSC) — Plan d'implémentation

> **Pour les exécutants agentiques :** SOUS-COMPÉTENCE REQUISE : utiliser
> superpowers:subagent-driven-development (recommandé) ou
> superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les
> étapes utilisent la syntaxe case à cocher (`- [ ]`) pour le suivi.

**Objectif :** Remplacer la simulation 100 % mock de `/connections` par un
vrai flow OAuth Google (scopes lecture seule GA4/GSC), permettant au
propriétaire d'un workspace de connecter un compte Google réel et
d'assigner ses ressources (propriétés GA4/Search Console) aux sites suivis.

**Architecture :** Réutilisation maximale de l'infrastructure déjà livrée
(chiffrement AES-GCM, découverte de ressources `GET /google/resources`,
liaison site↔ressource `POST /websites/{id}/link-resource`, consommation
dans `RealAuditProbe` — tout déjà scopé par workspace, aucun changement).
Nouveau : les 2 endpoints d'entrée/sortie du flow OAuth de données
(distincts du login), un endpoint de déconnexion, et la vraie UI frontend.

**Tech Stack :** FastAPI async / SQLAlchemy 2.0 / Alembic (aucune nouvelle
migration — la colonne `oauth_states.workspace_id` existe déjà) ; Next.js
16 / React 19 côté frontend, en réutilisant les composants
`components/connections/*` déjà maquettés.

**Spec :** `docs/superpowers/specs/2026-09-16-google-data-connections-design.md`

## Contraintes globales

- **GTM explicitement hors périmètre** — pas de scope `tagmanager.readonly`,
  pas de section GTM dans la vraie UI.
- **Réservé au propriétaire** (`role == "owner"`) — connecter, changer une
  ressource, déconnecter.
- **Connexions partagées au niveau workspace** — un seul jeu de connexions
  visible par tous les membres.
- **Déconnexion = révocation douce** (`status=revoked`), jamais de
  suppression de ligne — `ConnectionStatus.REVOKED` existe déjà dans
  l'enum, `RealAuditProbe._access_token` traite déjà tout statut
  non-`ACTIVE` comme dégradé.
- **`ruff check app tests` propre à chaque tâche** ; `pytest -W error`
  vert à chaque tâche backend.
- **Pas de placeholder / pas de code à écrire "plus tard"** dans aucune
  tâche.

---

### Task 1 : `workspace_id` exposé sur `GET /websites`

**Fichiers :**
- Modifier : `backend/app/api/v1/endpoints/websites.py:62-74` (classe `WebsiteOut`)
- Test : `backend/tests/test_websites.py`
- Modifier : `frontend/lib/api/dto.ts` (interface `WebsiteDto`)
- Modifier : `frontend/lib/mock/types.ts` (interface `Workspace`)
- Modifier : `frontend/lib/api/websites.ts` (`websiteToWorkspace`)

**Interfaces :**
- Produit : `Website.workspace_id` visible dans le JSON de `GET /websites`
  et `POST /websites` (les deux utilisent `WebsiteOut`/`CreateWebsiteDto`
  qui héritent du même schéma de base — vérifier que `CreateWebsiteDto`
  côté frontend a aussi le champ, voir Step 4).
- Produit côté frontend : `Workspace.realWorkspaceId: string` — nom
  délibérément distinct de `Workspace.id`/`websiteId` existants (qui
  identifient le *site*, pas le vrai workspace multi-tenant — voir la
  note terminologique de la spec §3.0).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# backend/tests/test_websites.py — ajouter, a cote de test_create_runs_first_audit_and_returns_snapshot
async def test_list_websites_exposes_workspace_id(
    authed_client: tuple[AsyncClient, User],
    db_session: AsyncSession,
    fake_detector: None,
) -> None:
    client, user = authed_client
    await client.post("/api/v1/websites", json={"name": "X", "domain": "expose-wsid.test"})
    resp = await client.get("/api/v1/websites")
    body = next(w for w in resp.json() if w["domain"] == "expose-wsid.test")
    assert body["workspace_id"] == str(await owner_workspace_id(db_session, user))
```

Run : `cd backend && .venv/Scripts/python.exe -m pytest tests/test_websites.py -k workspace_id -v`
Attendu : FAIL (`KeyError: 'workspace_id'` — le champ n'existe pas encore).

- [ ] **Step 2 : Ajouter le champ au schéma backend**

```python
# backend/app/api/v1/endpoints/websites.py — dans WebsiteOut
class WebsiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID  # NOUVEAU
    domain: str
    display_name: str
    detected_stack: StackKind | None
    stack_label: str | None
    allow_insecure_probe: bool
    ssl_status: str | None
    ssl_expires_at: datetime | None
    ssl_checked_at: datetime | None
    archived_at: datetime | None
```
`Website.workspace_id` existe déjà sur le modèle ORM (colonne réelle
depuis la migration auth/workspaces) — `from_attributes=True` le sérialise
automatiquement, aucun autre changement backend nécessaire (tous les
endpoints qui renvoient `WebsiteOut` renvoient déjà des instances ORM
`Website`, jamais des dicts construits à la main).

- [ ] **Step 3 : Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_websites.py -v
uv run ruff check app tests
```
Attendu : le test du Step 1 passe, `CreateWebsiteDto` (qui utilise le même
schéma dans `POST /websites`) aussi mis à jour sans effort supplémentaire.

- [ ] **Step 4 : Reporter le champ côté frontend**

```typescript
// frontend/lib/api/dto.ts — dans WebsiteDto
export interface WebsiteDto {
  id: string;
  workspace_id: string;  // NOUVEAU
  domain: string;
  display_name: string;
  detected_stack: string | null;
  stack_label: string | null;
  allow_insecure_probe: boolean;
  ssl_status: string | null;
  ssl_expires_at: string | null;
  ssl_checked_at: string | null;
  archived_at: string | null;
}
```

```typescript
// frontend/lib/mock/types.ts — dans l'interface Workspace, apres websiteId
export interface Workspace {
  id: string;
  name: string;
  domain: string;
  stack: StackId;
  tokenStatus: TokenStatus;
  websiteId?: string;
  /** Vrai workspace multi-tenant (backend) auquel appartient ce site —
   * distinct de `id`/`websiteId` qui identifient le SITE, pas le
   * workspace. Absent pour un site de demo (mock, non lie a un vrai
   * backend). Voir la note terminologique de la spec §3.0. */
  realWorkspaceId?: string;
  stackLabel?: string | null;
  sslStatus?: SslStatus | null;
  sslExpiresAt?: string | null;
}
```

```typescript
// frontend/lib/api/websites.ts — dans websiteToWorkspace()
export function websiteToWorkspace(
  dto: WebsiteDto | CreateWebsiteDto,
): Workspace {
  registerWebsite(dto.domain, dto.id);
  const sslStatus = "ssl" in dto ? dto.ssl.status : dto.ssl_status;
  const sslExpiresAt = "ssl" in dto ? dto.ssl.expires_at : dto.ssl_expires_at;
  return {
    id: dto.id,
    websiteId: dto.id,
    realWorkspaceId: dto.workspace_id,  // NOUVEAU
    name: dto.display_name,
    domain: dto.domain,
    stack: mapStack(dto.detected_stack),
    stackLabel: dto.stack_label,
    sslStatus: (sslStatus ?? null) as SslStatus | null,
    sslExpiresAt: sslExpiresAt ?? null,
    tokenStatus: "needs_reauth",
  };
}
```
Vérifier aussi `CreateWebsiteDto` dans `dto.ts` (le type utilisé par la
réponse de `POST /websites`) — probablement une interface séparée avec un
sous-champ `ssl` au lieu de `ssl_status` à plat ; lui ajouter
`workspace_id: string` de la même façon si elle ne l'a pas déjà via
héritage.

- [ ] **Step 5 : Build + lint frontend**

```bash
cd frontend
npm run build
npm run lint
```
Attendu : 0 erreur, 0 warning.

- [ ] **Step 6 : Commit**

```bash
git add backend/app/api/v1/endpoints/websites.py backend/tests/test_websites.py frontend/lib/api/dto.ts frontend/lib/mock/types.ts frontend/lib/api/websites.ts
git commit -m "feat(websites): expose workspace_id sur GET/POST /websites"
```

---

### Task 2 : `require_owner` partagé dans `app/services/workspaces.py`

**Fichiers :**
- Modifier : `backend/app/services/workspaces.py`
- Modifier : `backend/app/api/v1/endpoints/workspaces.py`
- Test : `backend/tests/test_workspaces_endpoints.py` (aucun nouveau test
  requis — les tests existants de garde propriétaire couvrent déjà ce
  chemin ; ce refactor ne doit PAS les casser)

**Interfaces :**
- Produit : `app.services.workspaces.require_owner(session, *,
  workspace_id: UUID, user_id: UUID) -> None` (lève `HTTPException` 404 si
  non-membre, 403 si membre non-owner).
- Consommé par : Task 5 et 6 (`connections.py`).

- [ ] **Step 1 : Déplacer la fonction**

Dans `backend/app/services/workspaces.py`, ajouter après `owned_website` :

```python
async def require_owner(session: AsyncSession, *, workspace_id: UUID, user_id: UUID) -> None:
    if not await is_member(session, workspace_id=workspace_id, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace introuvable")
    role = (
        await session.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="reserve au proprietaire")
```
`HTTPException`/`status`/`select` déjà importés dans ce fichier (utilisés
par `owned_website`) — aucun nouvel import.

- [ ] **Step 2 : Retirer l'ancienne copie et mettre à jour les appels**

Dans `backend/app/api/v1/endpoints/workspaces.py` :
1. Supprimer la fonction `_require_owner` (lignes 44-55).
2. Ajouter `require_owner` à l'import existant : `from app.services.workspaces import is_member, require_owner`.
3. Ligne 77 : `await _require_owner(session, workspace_id, user.id)` →
   `await require_owner(session, workspace_id=workspace_id, user_id=user.id)`.
4. Ligne 120 : même changement.

- [ ] **Step 3 : Run + ruff (pas de nouveau test — vérifier l'absence de régression)**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_workspaces_endpoints.py -v
uv run ruff check app tests
```
Attendu : les 12 tests existants (garde propriétaire incluse) passent
sans modification — le comportement est strictement identique, seul
l'emplacement du code change.

- [ ] **Step 4 : Commit**

```bash
git add backend/app/services/workspaces.py backend/app/api/v1/endpoints/workspaces.py
git commit -m "refactor(workspaces): require_owner partage dans la couche services"
```

---

### Task 3 : Scopes de la connexion de données

**Fichiers :**
- Modifier : `backend/app/services/google_oauth/base.py`
- Test : `backend/tests/test_google_oauth_scopes.py` (nouveau, minuscule)

**Interfaces :**
- Produit : `GOOGLE_DATA_SCOPES: tuple[str, ...]` — consommé par Task 5.

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# backend/tests/test_google_oauth_scopes.py
from app.services.google_oauth.base import GOOGLE_DATA_SCOPES, GOOGLE_LOGIN_SCOPES


def test_data_scopes_include_identity_and_readonly_apis() -> None:
    assert "openid" in GOOGLE_DATA_SCOPES
    assert "email" in GOOGLE_DATA_SCOPES
    assert "https://www.googleapis.com/auth/analytics.readonly" in GOOGLE_DATA_SCOPES
    assert "https://www.googleapis.com/auth/webmasters.readonly" in GOOGLE_DATA_SCOPES
    assert not any("tagmanager" in scope for scope in GOOGLE_DATA_SCOPES)


def test_data_scopes_distinct_from_login_scopes() -> None:
    assert GOOGLE_DATA_SCOPES != GOOGLE_LOGIN_SCOPES
```

Run : `pytest tests/test_google_oauth_scopes.py -v`
Attendu : FAIL (`ImportError: cannot import name 'GOOGLE_DATA_SCOPES'`).

- [ ] **Step 2 : Ajouter la constante**

```python
# backend/app/services/google_oauth/base.py — a cote de GOOGLE_LOGIN_SCOPES
GOOGLE_LOGIN_SCOPES: tuple[str, ...] = ("openid", "email", "profile")

# Scopes lecture seule pour la connexion de DONNEES (GA4/GSC), distincte du
# login ci-dessus. Pas de scope Tag Manager : aucune fonctionnalite livree
# n'appelle l'API GTM (export/check statique/verification headless
# travaillent directement sur la page rendue) — voir spec 2026-09-16.
GOOGLE_DATA_SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
)
```

- [ ] **Step 3 : Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_google_oauth_scopes.py -v
uv run ruff check app tests
```

- [ ] **Step 4 : Commit**

```bash
git add backend/app/services/google_oauth/base.py backend/tests/test_google_oauth_scopes.py
git commit -m "feat(google-oauth): scopes de la connexion de donnees (GA4/GSC, sans GTM)"
```

---

### Task 4 : `workspace_id` sur la transaction OAuth

**Fichiers :**
- Modifier : `backend/app/services/oauth_state.py`
- Modifier : `backend/app/api/v1/endpoints/auth.py:48-53` (call site du login)
- Test : `backend/tests/test_oauth_state.py` (nouveau)

**Interfaces :**
- Produit : `create_oauth_transaction(..., *, workspace_id: UUID | None,
  ...)`, `ConsumedOAuthState.workspace_id: UUID | None` — consommé par
  Task 5.
- Consomme : `OAuthState.workspace_id` (colonne déjà présente en base,
  migration `1d03150b69e5`, jamais lue/écrite jusqu'ici).

- [ ] **Step 1 : Écrire le test qui échoue**

```python
# backend/tests/test_oauth_state.py
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.oauth_state import consume_oauth_state, create_oauth_transaction


async def test_transaction_roundtrips_workspace_id(db_session: AsyncSession) -> None:
    workspace_id = uuid4()
    transaction = await create_oauth_transaction(
        db_session, user_id=None, workspace_id=workspace_id,
        redirect_to="/connections", ttl_seconds=600,
    )
    await db_session.commit()
    consumed = await consume_oauth_state(db_session, transaction.state)
    assert consumed is not None
    assert consumed.workspace_id == workspace_id


async def test_transaction_workspace_id_defaults_to_none_for_login(db_session: AsyncSession) -> None:
    transaction = await create_oauth_transaction(
        db_session, user_id=None, workspace_id=None,
        redirect_to=None, ttl_seconds=600,
    )
    await db_session.commit()
    consumed = await consume_oauth_state(db_session, transaction.state)
    assert consumed is not None
    assert consumed.workspace_id is None
```

Run : `pytest tests/test_oauth_state.py -v`
Attendu : FAIL (`TypeError: create_oauth_transaction() missing 1 required
keyword-only argument: 'workspace_id'` une fois le Step 2 fait dans le
mauvais ordre — pour l'instant, avant tout changement, le test échoue par
absence du paramètre : `TypeError: create_oauth_transaction() got an
unexpected keyword argument 'workspace_id'`).

- [ ] **Step 2 : Étendre le service**

```python
# backend/app/services/oauth_state.py
@dataclass(frozen=True, slots=True)
class ConsumedOAuthState:
    code_verifier: str
    user_id: UUID | None
    workspace_id: UUID | None
    redirect_to: str | None


async def create_oauth_transaction(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    workspace_id: UUID | None,
    redirect_to: str | None,
    ttl_seconds: int,
) -> OAuthTransaction:
    state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce_pair()
    session.add(
        OAuthState(
            state=state,
            code_verifier=verifier,
            user_id=user_id,
            workspace_id=workspace_id,
            redirect_to=redirect_to,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
    )
    await session.flush()
    return OAuthTransaction(state=state, code_challenge=challenge)


async def consume_oauth_state(session: AsyncSession, state: str) -> ConsumedOAuthState | None:
    row = (
        await session.execute(select(OAuthState).where(OAuthState.state == state))
    ).scalar_one_or_none()
    if row is None:
        return None
    snapshot = ConsumedOAuthState(
        code_verifier=row.code_verifier,
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        redirect_to=row.redirect_to,
    )
    expired = row.expires_at < datetime.now(UTC)
    await session.delete(row)
    await session.flush()
    return None if expired else snapshot
```

- [ ] **Step 3 : Mettre à jour le call site du login**

```python
# backend/app/api/v1/endpoints/auth.py, dans google_start (~ligne 48)
transaction = await create_oauth_transaction(
    session,
    user_id=None,
    workspace_id=None,  # NOUVEAU — le login n'est jamais scope a un workspace
    redirect_to=redirect_to,
    ttl_seconds=settings.oauth_state_ttl_seconds,
)
```

- [ ] **Step 4 : Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_oauth_state.py tests/test_auth_flow.py tests/test_auth_google_login.py -v
uv run ruff check app tests
```
Attendu : nouveaux tests verts, tests existants du login (`test_auth_flow.py`,
`test_auth_google_login.py`) toujours verts sans modification (changement
additif).

- [ ] **Step 5 : Commit**

```bash
git add backend/app/services/oauth_state.py backend/app/api/v1/endpoints/auth.py backend/tests/test_oauth_state.py
git commit -m "feat(oauth): transaction liee a un workspace (colonne deja en base)"
```

---

### Task 5 : Endpoints `GET /connections/google/start` + `GET /connections/google/callback`

**Fichiers :**
- Créer : `backend/app/api/v1/endpoints/connections.py`
- Modifier : `backend/app/api/v1/router.py`
- Test : `backend/tests/test_connections_google_start.py` (nouveau)
- Test : `backend/tests/test_connections_google_callback.py` (nouveau)

**Interfaces :**
- Consomme : `require_owner` (Task 2), `GOOGLE_DATA_SCOPES` (Task 3),
  `create_oauth_transaction`/`consume_oauth_state` (Task 4),
  `upsert_google_connection` (déjà existant,
  `app.services.connections`), `CurrentUserDep`/`SessionDep`/
  `SettingsDep`/`GoogleClientDep`/`TokenCipherDep` (déjà existants,
  `app.api.deps`).
- Produit : `router` (préfixe `/connections`) — enregistré dans Task 5,
  étendu avec l'endpoint de déconnexion en Task 6.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# backend/tests/test_connections_google_start.py
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace_member import WorkspaceMember
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def test_start_requires_owner_role(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession, make_user,
) -> None:
    client, user = authed_client
    other_owner = await make_user(sub="other-owner-conn")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(WorkspaceMember(workspace_id=other_ws, user_id=user.id, role="member"))
    await db_session.flush()

    resp = await client.get("/api/v1/connections/google/start", params={"workspace_id": str(other_ws)})
    assert resp.status_code == 403


async def test_start_rejects_non_member_workspace(
    authed_client: tuple[AsyncClient, "User"],
) -> None:
    client, _ = authed_client
    resp = await client.get("/api/v1/connections/google/start", params={"workspace_id": str(uuid4())})
    assert resp.status_code == 404


async def test_start_owner_gets_data_scopes(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    resp = await client.get("/api/v1/connections/google/start", params={"workspace_id": str(ws_id)})
    assert resp.status_code == 200
    params = _query(resp.json()["authorization_url"])
    scopes = params["scope"].split()
    assert "https://www.googleapis.com/auth/analytics.readonly" in scopes
    assert "https://www.googleapis.com/auth/webmasters.readonly" in scopes
    assert not any("tagmanager" in s for s in scopes)


async def test_start_requires_authentication(db_client: AsyncClient) -> None:
    resp = await db_client.get("/api/v1/connections/google/start", params={"workspace_id": str(uuid4())})
    assert resp.status_code == 401
```

```python
# backend/tests/test_connections_google_callback.py
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _start(client: AsyncClient, workspace_id) -> str:
    resp = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(workspace_id)}
    )
    assert resp.status_code == 200, resp.text
    return _query(resp.json()["authorization_url"])["state"]


async def test_callback_creates_connection(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    state = await _start(client, ws_id)

    resp = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/connections")

    conn = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id)
        )
    ).scalar_one()
    assert conn.google_account_email == "client.perso@gmail.com"
    assert conn.status == ConnectionStatus.ACTIVE


async def test_callback_reconnect_reactivates_revoked_connection(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)

    state1 = await _start(client, ws_id)
    await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state1},
        follow_redirects=False,
    )
    conn = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id)
        )
    ).scalar_one()
    conn.status = ConnectionStatus.REVOKED
    await db_session.commit()

    state2 = await _start(client, ws_id)
    resp2 = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state2},
        follow_redirects=False,
    )
    assert resp2.status_code == 302

    conns = (
        await db_session.execute(
            select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id)
        )
    ).scalars().all()
    assert len(conns) == 1  # pas de doublon
    assert conns[0].status == ConnectionStatus.ACTIVE  # reactivee


async def test_callback_rejects_denied_consent(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    await _start(client, ws_id)  # cree une transaction (state non utilise ici)
    resp = await client.get(
        "/api/v1/connections/google/callback",
        params={"error": "access_denied", "state": "peu-importe"},
    )
    assert resp.status_code == 400


async def test_callback_rejects_invalid_state(authed_client: tuple[AsyncClient, "User"]) -> None:
    client, _ = authed_client
    resp = await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": "invalide"},
    )
    assert resp.status_code == 400
```

Run : `pytest tests/test_connections_google_start.py tests/test_connections_google_callback.py -v`
Attendu : FAIL (`404 Not Found` — le router n'existe pas encore, chemin inconnu).

- [ ] **Step 2 : Créer l'endpoint**

```python
# backend/app/api/v1/endpoints/connections.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, GoogleClientDep, SessionDep, SettingsDep, TokenCipherDep
from app.services.connections import upsert_google_connection
from app.services.google_oauth import InvalidGrantError
from app.services.google_oauth.base import GOOGLE_DATA_SCOPES
from app.services.oauth_state import consume_oauth_state, create_oauth_transaction
from app.services.workspaces import require_owner

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectionStartResponse(BaseModel):
    authorization_url: str


@router.get("/google/start", response_model=ConnectionStartResponse)
async def connections_google_start(
    workspace_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
) -> ConnectionStartResponse:
    await require_owner(session, workspace_id=workspace_id, user_id=user.id)
    transaction = await create_oauth_transaction(
        session,
        user_id=user.id,
        workspace_id=workspace_id,
        redirect_to="/connections",
        ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    await session.commit()
    url = client.build_authorization_url(
        state=transaction.state,
        code_challenge=transaction.code_challenge,
        scopes=GOOGLE_DATA_SCOPES,
    )
    return ConnectionStartResponse(authorization_url=url)


@router.get("/google/callback")
async def connections_google_callback(
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
    cipher: TokenCipherDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"consentement Google refuse : {error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="code ou state manquant"
        )
    consumed = await consume_oauth_state(session, state)
    if consumed is None:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="state OAuth invalide, expire ou deja utilise",
        )
    if consumed.workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transaction OAuth invalide pour une connexion de donnees",
        )
    try:
        token = await client.exchange_code(code=code, code_verifier=consumed.code_verifier)
    except InvalidGrantError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="code d'autorisation invalide"
        ) from None
    if token.refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google n'a pas fourni de refresh token — reconsentement requis",
        )
    userinfo = await client.fetch_userinfo(access_token=token.access_token)
    await upsert_google_connection(
        session,
        workspace_id=consumed.workspace_id,
        userinfo=userinfo,
        token=token,
        cipher=cipher,
    )
    await session.commit()
    return RedirectResponse(
        url=consumed.redirect_to or settings.frontend_base_url,
        status_code=status.HTTP_302_FOUND,
    )
```

Câbler le router dans `backend/app/api/v1/router.py` : importer
`connections` à côté des autres modules d'endpoints et
`api_router.include_router(connections.router)`, suivant exactement le
pattern déjà utilisé pour `workspaces.router`.

- [ ] **Step 3 : Run + ruff**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_connections_google_start.py tests/test_connections_google_callback.py -v
uv run ruff check app tests
```
Attendu : tous les tests passent.

- [ ] **Step 4 : Suite complète**

```bash
.venv/Scripts/python.exe -m pytest -W error -q
```
Attendu : aucune régression sur le reste de la suite (login, workspaces,
invitations, etc.).

- [ ] **Step 5 : Commit**

```bash
git add backend/app/api/v1/endpoints/connections.py backend/app/api/v1/router.py backend/tests/test_connections_google_start.py backend/tests/test_connections_google_callback.py
git commit -m "feat(connections): flow OAuth de connexion de donnees GA4/GSC"
```

---

### Task 6 : Déconnexion — `DELETE /connections/{connection_id}`

**Fichiers :**
- Modifier : `backend/app/api/v1/endpoints/connections.py`
- Test : `backend/tests/test_connections_disconnect.py` (nouveau)

**Interfaces :**
- Consomme : `require_owner` (Task 2), `decrypt_refresh_token` (existant,
  `app.services.connections`), `GoogleClientDep.revoke()` (existant).
- Produit : `DELETE /connections/{connection_id}`.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# backend/tests/test_connections_disconnect.py
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.models.website import Website
from app.models.website_google_link import WebsiteGoogleLink
from app.models.workspace_member import WorkspaceMember
from tests.conftest import owner_workspace_id


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _connect(client: AsyncClient, workspace_id) -> "GoogleConnection":
    start = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(workspace_id)}
    )
    state = _query(start.json()["authorization_url"])["state"]
    await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )


async def test_disconnect_requires_owner(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession, make_user,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    await _connect(client, ws_id)
    conn = (
        await db_session.execute(select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id))
    ).scalar_one()

    other_owner = await make_user(sub="other-owner-disc")
    other_ws = await owner_workspace_id(db_session, other_owner)
    db_session.add(WorkspaceMember(workspace_id=ws_id, user_id=other_owner.id, role="member"))
    await db_session.flush()

    resp = await client.delete(f"/api/v1/connections/{conn.id}")
    assert resp.status_code == 200  # l'appelant EST le proprietaire ici : sanity check positif
    _ = other_ws  # utilise seulement pour construire un membre non-owner distinct


async def test_disconnect_marks_revoked_and_keeps_links(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession, fake_detector: None,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    await _connect(client, ws_id)
    conn = (
        await db_session.execute(select(GoogleConnection).where(GoogleConnection.workspace_id == ws_id))
    ).scalar_one()

    site_resp = await client.post("/api/v1/websites", json={"name": "S", "domain": "disc-test.example"})
    site_id = site_resp.json()["id"]
    db_session.add(
        WebsiteGoogleLink(
            website_id=site_id, google_connection_id=conn.id,
            resource_type="ga4_property", resource_id="properties/1",
        )
    )
    await db_session.flush()

    resp = await client.delete(f"/api/v1/connections/{conn.id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"

    await db_session.refresh(conn)
    assert conn.status == ConnectionStatus.REVOKED

    links = (
        await db_session.execute(select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == site_id))
    ).scalars().all()
    assert len(links) == 1  # jamais supprimee


async def test_disconnect_not_found(authed_client: tuple[AsyncClient, "User"]) -> None:
    client, _ = authed_client
    from uuid import uuid4
    resp = await client.delete(f"/api/v1/connections/{uuid4()}")
    assert resp.status_code == 404
```

Run : `pytest tests/test_connections_disconnect.py -v`
Attendu : FAIL (`405 Method Not Allowed` — l'endpoint n'existe pas).

- [ ] **Step 2 : Ajouter l'endpoint**

```python
# backend/app/api/v1/endpoints/connections.py — ajouter les imports necessaires
from uuid import UUID as UUID  # deja importe plus haut, ne pas dupliquer

from app.models.enums import ConnectionStatus
from app.models.google_connection import GoogleConnection
from app.services.connections import decrypt_refresh_token
```

```python
# a la suite de connections_google_callback
class DisconnectResponse(BaseModel):
    status: str


@router.delete("/{connection_id}", response_model=DisconnectResponse)
async def disconnect_connection(
    connection_id: UUID,
    user: CurrentUserDep,
    session: SessionDep,
    client: GoogleClientDep,
    cipher: TokenCipherDep,
) -> DisconnectResponse:
    connection = await session.get(GoogleConnection, connection_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="connexion introuvable"
        )
    await require_owner(session, workspace_id=connection.workspace_id, user_id=user.id)
    if connection.status == ConnectionStatus.ACTIVE:
        try:
            refresh_token = decrypt_refresh_token(connection, cipher=cipher)
            await client.revoke(token=refresh_token)
        except Exception:  # noqa: BLE001 — best-effort, l'intention locale prime (voir spec)
            pass
    connection.status = ConnectionStatus.REVOKED
    await session.commit()
    return DisconnectResponse(status="revoked")
```

- [ ] **Step 3 : Run + ruff + suite complète**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_connections_disconnect.py -v
uv run ruff check app tests
.venv/Scripts/python.exe -m pytest -W error -q
```

- [ ] **Step 4 : Commit**

```bash
git add backend/app/api/v1/endpoints/connections.py backend/tests/test_connections_disconnect.py
git commit -m "feat(connections): deconnexion (revocation douce)"
```

---

### Task 7 : Client API frontend + page intermédiaire OAuth

**Fichiers :**
- Créer : `frontend/lib/api/connections.ts`
- Créer : `frontend/app/connections/google/page.tsx`

**Interfaces :**
- Produit : `startGoogleConnection(workspaceId: string): Promise<void>`
  (fetch + `window.location.href`, pattern de `login/google/page.tsx`),
  `listGoogleResources()`, `linkResource(websiteId, body)`,
  `disconnectConnection(connectionId)`.

- [ ] **Step 1 : Client API**

```typescript
// frontend/lib/api/connections.ts
import { apiDelete, apiGet, apiPost } from "./client";

export interface ConnectionSummaryDto {
  id: string;
  email: string;
  status: "active" | "needs_reauth" | "revoked";
}

export interface Ga4PropertyDto {
  resource_id: string;
  display_name: string;
  account: string;
  account_display_name: string;
  source_connection_id: string;
  source_email: string;
}

export interface GscSiteDto {
  resource_id: string;
  permission_level: string;
  source_connection_id: string;
  source_email: string;
}

export interface ResourcesResponseDto {
  connections: ConnectionSummaryDto[];
  ga4_properties: Ga4PropertyDto[];
  gtm_containers: unknown[]; // toujours vide (pas de scope GTM), non affiche
  gsc_sites: GscSiteDto[];
}

export function listGoogleResources(): Promise<ResourcesResponseDto> {
  return apiGet<ResourcesResponseDto>("/google/resources");
}

export interface LinkResourceInput {
  google_connection_id: string;
  resource_type: "ga4_property" | "gsc_site";
  resource_id: string;
  resource_display_name?: string | null;
}

export function linkResource(websiteId: string, body: LinkResourceInput): Promise<unknown> {
  return apiPost(`/websites/${websiteId}/link-resource`, body);
}

export function disconnectConnection(connectionId: string): Promise<void> {
  return apiDelete(`/connections/${connectionId}`);
}
```
Note : `DELETE /connections/{id}` renvoie 200 avec un corps
(`{"status": "revoked"}`, Task 6), pas 204 (contrairement à
`DELETE /websites/{id}`, vérifié dans le code : celui-là est bien
`status_code=204` sans corps — ne pas généraliser à tort). Vérifié dans
`client.ts` : `apiDelete` n'appelle jamais `.json()` sur la réponse, quel
que soit son statut ou son corps — un corps 200 simplement non lu ne
lève aucune erreur. `apiDelete` convient donc tel quel ici ; aucune
fonction dédiée à écrire.

- [ ] **Step 2 : Page intermédiaire**

Copier exactement le composant `frontend/app/login/google/page.tsx`
(pattern déjà éprouvé : fetch de `authorization_url` dans un `useEffect`,
`window.location.href`, état d'erreur avec lien de retour) en l'adaptant :

```tsx
// frontend/app/connections/google/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { apiGet, ApiError } from "@/lib/api/client";

interface StartResponse {
  authorization_url: string;
}

export default function ConnectGoogleRedirectPage() {
  const searchParams = useSearchParams();
  const workspaceId = searchParams.get("workspace_id");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceId) {
      setError("workspace manquant");
      return;
    }
    let cancelled = false;
    apiGet<StartResponse>(`/connections/google/start?workspace_id=${workspaceId}`)
      .then(({ authorization_url }) => {
        if (!cancelled) window.location.href = authorization_url;
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Connexion Google impossible");
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 text-center">
      <div className="space-y-2">
        <p className="text-sm text-ink-muted">
          {error ?? "Redirection vers Google…"}
        </p>
        {error && (
          <a href="/connections" className="block text-xs text-ink-muted underline hover:text-ink">
            Retour aux connexions
          </a>
        )}
      </div>
    </div>
  );
}
```
`useSearchParams` dans un Client Component nécessite un wrapper
`<Suspense>` pour le rendu statique (même contrainte Next.js 16 déjà
rencontrée pour `register/page.tsx` avec le paramètre `invitation`) —
suivre exactement ce même pattern (composant interne + export par défaut
enveloppant dans `<Suspense fallback={null}>`).

- [ ] **Step 3 : Build + lint**

```bash
cd frontend
npm run build
npm run lint
```

- [ ] **Step 4 : Commit**

```bash
git add frontend/lib/api/connections.ts frontend/app/connections/google/page.tsx
git commit -m "feat(frontend): client API + page intermediaire pour la connexion Google donnees"
```

---

### Task 8 : Backend — liaisons actuelles d'un site + enrichir le résumé de connexion

Découvert en écrivant la Task 9 en détail : aucun endpoint ne renvoie les
liaisons `WebsiteGoogleLink` *actuelles* d'un site (`POST /link-resource`
ne renvoie que la liaison qu'on vient de créer, pas l'état complet) —
sans ça, le frontend ne peut pas savoir quelle ressource est déjà
assignée au chargement de la page. `ConnectionSummary` (`GET
/google/resources`) n'expose pas non plus `granted_scopes`/
`last_refreshed_at`, pourtant déjà des colonnes réelles sur
`GoogleConnection`.

**Fichiers :**
- Modifier : `backend/app/api/v1/endpoints/google.py`
- Test : `backend/tests/test_google_resources.py` (étendre le fichier
  existant — vérifier son nom exact avant d'écrire, il peut différer
  légèrement)

**Interfaces :**
- Produit : `GET /websites/{website_id}/google-links` →
  `list[WebsiteGoogleLinkOut]`.
- Produit : `ConnectionSummary` gagne `granted_scopes: list[str]`,
  `last_refreshed_at: datetime | None`.
- Consommé par Task 9.

- [ ] **Step 1 : Écrire les tests qui échouent**

```python
# a ajouter dans le fichier de test existant qui couvre GET /google/resources
def _query(url: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def test_resources_summary_includes_scopes_and_last_refresh(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)

    # Etablit une connexion active via le vrai flow HTTP start->callback
    # (meme sequence que test_connections_google_callback.py::test_callback_creates_connection,
    # ecrite en Task 5 — reprise ici telle quelle, pas de nouvel helper partage
    # cree pour eviter d'introduire une dependance entre fichiers de test).
    start = await client.get(
        "/api/v1/connections/google/start", params={"workspace_id": str(ws_id)}
    )
    state = _query(start.json()["authorization_url"])["state"]
    await client.get(
        "/api/v1/connections/google/callback",
        params={"code": "mock:client_perso", "state": state},
        follow_redirects=False,
    )

    resp = await client.get("/api/v1/google/resources")
    summary = resp.json()["connections"][0]
    assert summary["granted_scopes"] == [
        "openid", "email",
        "https://www.googleapis.com/auth/analytics.readonly",
    ]  # scopes de la fixture mock "client_perso", voir app/services/google_oauth/mock.py
    assert summary["last_refreshed_at"] is not None


async def test_website_google_links_returns_current_links(
    authed_client: tuple[AsyncClient, "User"], db_session: AsyncSession, fake_detector: None,
) -> None:
    client, user = authed_client
    ws_id = await owner_workspace_id(db_session, user)
    site_resp = await client.post("/api/v1/websites", json={"name": "L", "domain": "gg-links.test"})
    site_id = site_resp.json()["id"]

    resp = await client.get(f"/api/v1/websites/{site_id}/google-links")
    assert resp.status_code == 200
    assert resp.json() == []  # aucune liaison pour l'instant


async def test_website_google_links_requires_membership(
    authed_client: tuple[AsyncClient, "User"],
) -> None:
    from uuid import uuid4
    client, _ = authed_client
    resp = await client.get(f"/api/v1/websites/{uuid4()}/google-links")
    assert resp.status_code == 404
```
Run : `pytest tests/test_google_resources.py -k "scopes_and_last_refresh or google_links" -v`
Attendu : FAIL (`KeyError`/`404 Not Found`).

- [ ] **Step 2 : Étendre `ConnectionSummary`**

```python
# backend/app/api/v1/endpoints/google.py
from datetime import datetime  # ajouter a l'import existant si absent

class ConnectionSummary(BaseModel):
    id: UUID
    email: str
    status: ConnectionStatus
    granted_scopes: list[str]
    last_refreshed_at: datetime | None


def _summary(connection: GoogleConnection) -> ConnectionSummary:
    return ConnectionSummary(
        id=connection.id,
        email=connection.google_account_email,
        status=connection.status,
        granted_scopes=connection.granted_scopes,
        last_refreshed_at=connection.last_refreshed_at,
    )
```

- [ ] **Step 3 : Ajouter l'endpoint des liaisons actuelles**

```python
# backend/app/api/v1/endpoints/google.py — a la suite des classes existantes
class WebsiteGoogleLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    google_connection_id: UUID
    resource_type: ResourceType
    resource_id: str
    resource_display_name: str | None


@router.get("/websites/{website_id}/google-links", response_model=list[WebsiteGoogleLinkOut])
async def list_website_google_links(
    website_id: UUID, user: CurrentUserDep, session: SessionDep,
) -> list[WebsiteGoogleLink]:
    await owned_website(session, website_id=website_id, user_id=user.id)
    rows = (
        await session.execute(
            select(WebsiteGoogleLink).where(WebsiteGoogleLink.website_id == website_id)
        )
    ).scalars().all()
    return list(rows)
```
`owned_website` déjà importé dans ce fichier (`from
app.services.workspaces import owned_website, user_workspace_ids`).

- [ ] **Step 4 : Run + ruff + suite complète**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest tests/test_google_resources.py -v
uv run ruff check app tests
.venv/Scripts/python.exe -m pytest -W error -q
```

- [ ] **Step 5 : Commit**

```bash
git add backend/app/api/v1/endpoints/google.py backend/tests/test_google_resources.py
git commit -m "feat(google): endpoint des liaisons actuelles d'un site + scopes/derniere synchro"
```

---

### Task 9 : Vraie UI `/connections`

**Fichiers :**
- Modifier : `frontend/lib/api/connections.ts` (compléter les types du Step 1
  de Task 7 avec les champs ajoutés en Task 8)
- Modifier : `frontend/components/connections/connections-view.tsx`
- Modifier : `frontend/components/connections/identities-section.tsx`
- Modifier : `frontend/components/connections/identity-card.tsx`
- Modifier : `frontend/components/connections/resources-section.tsx`
- Modifier : `frontend/components/connections/resource-row.tsx`

**Interfaces :**
- Consomme : `listGoogleResources` (Task 7, étendu Task 8),
  `listWebsiteGoogleLinks` (nouveau, Task 8), `linkResource`,
  `disconnectConnection` (Task 7), `workspace.realWorkspaceId` (Task 1),
  `GET /workspaces/mine` (existant) pour `isOwner`.

Les composants existants (`connections-view.tsx`,
`identities-section.tsx`, `identity-card.tsx`, `resources-section.tsx`,
`resource-row.tsx`) sont déjà stylés et fonctionnels en mode mock — lus
intégralement pour écrire cette tâche (formes exactes ci-dessous, pas de
supposition).

- [ ] **Step 1 : Compléter le client API (Task 7 posait la base)**

```typescript
// frontend/lib/api/connections.ts — ajouter
export interface ConnectionSummaryDto {
  id: string;
  email: string;
  status: "active" | "needs_reauth" | "revoked";
  granted_scopes: string[];
  last_refreshed_at: string | null;
}

export interface WebsiteGoogleLinkDto {
  id: string;
  google_connection_id: string;
  resource_type: "ga4_property" | "gtm_container" | "gsc_site";
  resource_id: string;
  resource_display_name: string | null;
}

export function listWebsiteGoogleLinks(websiteId: string): Promise<WebsiteGoogleLinkDto[]> {
  return apiGet<WebsiteGoogleLinkDto[]>(`/websites/${websiteId}/google-links`);
}
```
(Remplace le `ConnectionSummaryDto` posé en Task 7 — même nom, champs
complétés.)

- [ ] **Step 2 : Réécrire `connections-view.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";

import { PageShell } from "@/components/shell/page-shell";
import {
  listGoogleResources,
  listWebsiteGoogleLinks,
  type ConnectionSummaryDto,
  type Ga4PropertyDto,
  type GscSiteDto,
  type WebsiteGoogleLinkDto,
} from "@/lib/api/connections";
import { apiGet } from "@/lib/api/client";
import { useShell } from "@/lib/shell/shell-context";

import { IdentitiesSection } from "./identities-section";
import { ResourcesSection } from "./resources-section";

interface WorkspaceMineDto {
  id: string;
  name: string;
  role: string;
}

export function ConnectionsView() {
  const { workspace } = useShell();
  const [status, setStatus] = useState<"loading" | "loaded">("loading");
  const [connections, setConnections] = useState<ConnectionSummaryDto[]>([]);
  const [ga4Properties, setGa4Properties] = useState<Ga4PropertyDto[]>([]);
  const [gscSites, setGscSites] = useState<GscSiteDto[]>([]);
  const [links, setLinks] = useState<WebsiteGoogleLinkDto[]>([]);
  const [isOwner, setIsOwner] = useState(false);

  async function load() {
    const [resources, myWorkspaces] = await Promise.all([
      listGoogleResources(),
      apiGet<WorkspaceMineDto[]>("/workspaces/mine"),
    ]);
    setConnections(resources.connections);
    setGa4Properties(resources.ga4_properties);
    setGscSites(resources.gsc_sites);
    setIsOwner(
      myWorkspaces.some((w) => w.id === workspace.realWorkspaceId && w.role === "owner"),
    );
    if (workspace.websiteId) {
      setLinks(await listWebsiteGoogleLinks(workspace.websiteId));
    }
    setStatus("loaded");
  }

  useEffect(() => {
    setStatus("loading");
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace.realWorkspaceId, workspace.websiteId]);

  if (status === "loading") return null;

  return (
    <PageShell
      title="Connexions Google"
      subtitle="Identités Google reliées et ressources GA4 / Search Console assignées à ce site. Accès en lecture seule."
    >
      <IdentitiesSection
        connections={connections}
        isOwner={isOwner}
        workspaceId={workspace.realWorkspaceId}
        onChanged={load}
      />
      <ResourcesSection
        key={workspace.id}
        siteName={workspace.name}
        websiteId={workspace.websiteId}
        ga4Properties={ga4Properties}
        gscSites={gscSites}
        links={links}
        isOwner={isOwner}
        onChanged={load}
      />
    </PageShell>
  );
}
```
Note : pas de section GTM (le contrat `ResourcesResponseDto` renvoie
`gtm_containers` — toujours vide sans le scope demandé, Task 3 — jamais
lu ici).

- [ ] **Step 3 : Réécrire `identities-section.tsx` + `identity-card.tsx`**

```tsx
// frontend/components/connections/identities-section.tsx
"use client";

import type { ConnectionSummaryDto } from "@/lib/api/connections";

import { GoogleGlyph } from "./google-glyph";
import { IdentityCard } from "./identity-card";

export function IdentitiesSection({
  connections,
  isOwner,
  workspaceId,
  onChanged,
}: {
  connections: ConnectionSummaryDto[];
  isOwner: boolean;
  workspaceId: string | undefined;
  onChanged: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-ink">Comptes Google liés</h2>
        {isOwner && workspaceId && (
          <a
            href={`/connections/google?workspace_id=${workspaceId}`}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
          >
            <GoogleGlyph className="size-3.5" />
            Connecter un autre compte Google
          </a>
        )}
      </div>

      <div className="space-y-3">
        {connections.map((connection) => (
          <IdentityCard
            key={connection.id}
            connection={connection}
            isOwner={isOwner}
            workspaceId={workspaceId}
            onChanged={onChanged}
          />
        ))}
        {connections.length === 0 && (
          <p className="text-xs text-ink-muted">Aucun compte Google connecté.</p>
        )}
      </div>
    </section>
  );
}
```
Le bouton "Connecter" devient un `<a>` (navigation plein-navigateur, même
raison que `/login/google` : le flow OAuth exige une vraie redirection,
un `fetch` ne peut pas la suivre), pas un `onClick` avec toast comme dans
le mock.

```tsx
// frontend/components/connections/identity-card.tsx
"use client";

import { Plug, RotateCw } from "lucide-react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { disconnectConnection, type ConnectionSummaryDto } from "@/lib/api/connections";
import { relativeHours } from "@/lib/format";
import { cn } from "@/lib/utils";

import { GoogleGlyph } from "./google-glyph";

/** `relativeHours` (lib/format.ts, deja utilise par identity-card en mode
 * mock) attend un nombre d'heures — converti ici depuis le timestamp reel. */
function hoursAgo(iso: string | null): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000));
}

export function IdentityCard({
  connection,
  isOwner,
  workspaceId,
  onChanged,
}: {
  connection: ConnectionSummaryDto;
  isOwner: boolean;
  workspaceId: string | undefined;
  onChanged: () => void;
}) {
  const active = connection.status === "active";
  const needsReauth = connection.status === "needs_reauth";
  const hours = hoursAgo(connection.last_refreshed_at);

  async function handleDisconnect() {
    try {
      await disconnectConnection(connection.id);
      toast("Compte déconnecté", { description: connection.email });
      onChanged();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Déconnexion impossible");
    }
  }

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-ink-muted">
            <GoogleGlyph className="size-4" />
          </span>
          <p className="text-sm font-medium text-ink">{connection.email}</p>
        </div>

        {isOwner &&
          (needsReauth && workspaceId ? (
            <a
              href={`/connections/google?workspace_id=${workspaceId}`}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-warn/40 bg-warn/10 px-2.5 text-xs font-medium text-warn shadow-sm transition-colors hover:bg-warn/15"
            >
              <RotateCw className="size-3.5" />
              Re-synchroniser
            </a>
          ) : active ? (
            <button
              type="button"
              onClick={() => void handleDisconnect()}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
            >
              <Plug className="size-3.5" />
              Déconnecter
            </button>
          ) : null)}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {connection.granted_scopes.map((scope) => (
          <span
            key={scope}
            className="inline-flex h-[18px] items-center rounded border border-hairline bg-white/[0.03] px-1.5 font-mono text-2xs text-ink-muted"
          >
            {scope.replace("https://www.googleapis.com/auth/", "")}
          </span>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-white/[0.06] pt-3 text-xs">
        <span className="flex items-center gap-2 font-medium">
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              active ? "bg-ok" : "bg-warn",
            )}
          />
          <span className={active ? "text-ok" : "text-warn"}>
            {active ? "Actif" : needsReauth ? "Re-authentification requise" : "Déconnecté"}
          </span>
        </span>
        {hours !== null && (
          <>
            <span className="text-ink-faint">·</span>
            <span className="text-ink-faint">synchro {relativeHours(hours)}</span>
          </>
        )}
      </div>
    </div>
  );
}
```
`role` (mock : note humaine libre "Agence — accès délégué") est
délibérément retiré — aucune donnée backend ne le supporte, l'inventer
serait fabriquer de l'information.

- [ ] **Step 4 : Réécrire `resources-section.tsx` + `resource-row.tsx`**

```tsx
// frontend/components/connections/resources-section.tsx
"use client";

import { toast } from "sonner";

import { linkResource, type Ga4PropertyDto, type GscSiteDto, type WebsiteGoogleLinkDto } from "@/lib/api/connections";
import { ApiError } from "@/lib/api/client";

import { ResourceRow } from "./resource-row";

export function ResourcesSection({
  siteName,
  websiteId,
  ga4Properties,
  gscSites,
  links,
  isOwner,
  onChanged,
}: {
  siteName: string;
  websiteId: string | undefined;
  ga4Properties: Ga4PropertyDto[];
  gscSites: GscSiteDto[];
  links: WebsiteGoogleLinkDto[];
  isOwner: boolean;
  onChanged: () => void;
}) {
  async function handleChange(
    type: "ga4_property" | "gsc_site",
    resourceId: string,
    connectionId: string,
    displayName: string,
  ) {
    if (!websiteId) return;
    try {
      await linkResource(websiteId, {
        google_connection_id: connectionId,
        resource_type: type,
        resource_id: resourceId,
        resource_display_name: displayName,
      });
      toast("Ressource réassignée", { description: displayName });
      onChanged();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Liaison impossible");
    }
  }

  const ga4Link = links.find((l) => l.resource_type === "ga4_property") ?? null;
  const gscLink = links.find((l) => l.resource_type === "gsc_site") ?? null;

  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-sm font-medium text-ink">
          Ressources assignées à {siteName}
        </h2>
        <p className="max-w-2xl text-xs leading-relaxed text-ink-muted">
          Chaque ressource peut provenir d&apos;un compte Google différent sans
          collision.
        </p>
      </div>

      <div className="space-y-3">
        <ResourceRow
          typeLabel="Google Analytics 4"
          typeNoun="Propriété liée"
          resourceType="ga4_property"
          options={ga4Properties.map((p) => ({
            id: p.resource_id,
            label: p.display_name,
            connectionId: p.source_connection_id,
            sourceEmail: p.source_email,
          }))}
          linked={ga4Link}
          isOwner={isOwner}
          onChange={handleChange}
        />
        <ResourceRow
          typeLabel="Google Search Console"
          typeNoun="Domaine vérifié"
          resourceType="gsc_site"
          options={gscSites.map((s) => ({
            id: s.resource_id,
            label: s.resource_id,
            connectionId: s.source_connection_id,
            sourceEmail: s.source_email,
          }))}
          linked={gscLink}
          isOwner={isOwner}
          onChange={handleChange}
        />
      </div>
    </section>
  );
}
```

```tsx
// frontend/components/connections/resource-row.tsx
"use client";

import { ChevronDown, LineChart, Search, type LucideIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { WebsiteGoogleLinkDto } from "@/lib/api/connections";

const ICON: Record<"ga4_property" | "gsc_site", LucideIcon> = {
  ga4_property: LineChart,
  gsc_site: Search,
};

interface Option {
  id: string;
  label: string;
  connectionId: string;
  sourceEmail: string;
}

export function ResourceRow({
  typeLabel,
  typeNoun,
  resourceType,
  options,
  linked,
  isOwner,
  onChange,
}: {
  typeLabel: string;
  typeNoun: string;
  resourceType: "ga4_property" | "gsc_site";
  options: Option[];
  linked: WebsiteGoogleLinkDto | null;
  isOwner: boolean;
  onChange: (type: "ga4_property" | "gsc_site", resourceId: string, connectionId: string, displayName: string) => void;
}) {
  const Icon = ICON[resourceType];
  const linkedOption = options.find((o) => o.id === linked?.resource_id) ?? null;

  return (
    <div className="rounded-xl border border-white/[0.08] bg-surface/60 p-5 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-ink-muted">
            <Icon className="size-4" />
          </span>
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-ink">{typeLabel}</p>
            <p className="text-xs text-ink-faint">{typeNoun}</p>
          </div>
        </div>

        {isOwner && options.length > 0 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-xs font-medium text-ink-muted shadow-sm transition-colors hover:bg-white/[0.06] hover:text-ink"
              >
                Changer
                <ChevronDown className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuLabel className="text-2xs font-medium text-ink-faint">
                Ressources {typeLabel} découvertes
              </DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={linked?.resource_id ?? ""}
                onValueChange={(value) => {
                  const option = options.find((o) => o.id === value);
                  if (option) onChange(resourceType, option.id, option.connectionId, option.label);
                }}
              >
                {options.map((option) => (
                  <DropdownMenuRadioItem
                    key={option.id}
                    value={option.id}
                    className="flex-col items-start gap-0.5 py-2"
                  >
                    <span className="text-xs font-medium text-ink">{option.label}</span>
                    <span className="font-mono text-2xs text-ink-faint">{option.id}</span>
                    <span className="text-2xs text-ink-faint">via {option.sourceEmail}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      <div className="mt-4 border-t border-white/[0.06] pt-3">
        {linked ? (
          <div className="space-y-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-medium text-ink">
                {linkedOption?.label ?? linked.resource_display_name ?? linked.resource_id}
              </span>
              <span className="font-mono text-2xs text-ink-muted">{linked.resource_id}</span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Aucune ressource assignée.</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5 : Build + lint**

```bash
cd frontend
npm run build
npm run lint
```
Attendu : 0 erreur, 0 warning. Si `linkResource`/`disconnectConnection`
posés en Task 7 ont une signature légèrement différente de celle utilisée
ici, ajuster l'un ou l'autre pour cohérence — Task 7 est plus récente dans
l'historique donc plus probablement juste, mais vérifier concrètement
plutôt que supposer.

- [ ] **Step 6 : Commit**

```bash
git add frontend/lib/api/connections.ts frontend/components/connections/
git commit -m "feat(frontend): vraie UI /connections branchee sur le backend"
```

---

### Task 10 : Vérification finale

**Fichiers :** aucun changement de code — vérification uniquement.

- [ ] **Step 1 : Suite backend complète, deux fois**

```bash
cd backend && export PATH="$PATH:/c/Users/DELL/AppData/Roaming/Python/Python312/Scripts"
.venv/Scripts/python.exe -m pytest -W error -q
.venv/Scripts/python.exe -m pytest -W error -q
uv run ruff check app tests
uv run alembic check
```
Attendu : même nombre de tests verts sur les deux runs, 0 erreur ruff,
`alembic check` propre (rappel : aucune migration dans ce plan, la colonne
`workspace_id` existait déjà).

- [ ] **Step 2 : Frontend**

```bash
cd frontend
npm run build
npm run lint
```

- [ ] **Step 3 : Smoke test manuel avec un vrai compte Google (backend + frontend déployés ou en local avec `GOOGLE_OAUTH_MOCK=false`)**

1. Sur `/connections`, en tant que propriétaire : cliquer "Connecter un
   compte Google" → vrai écran de consentement Google (scopes Analytics +
   Search Console visibles, PAS Tag Manager) → retour sur `/connections`
   avec la connexion listée (email réel, statut actif).
2. Sélectionner une vraie ressource GA4 et/ou une propriété Search Console
   pour un site suivi via "Changer".
3. Aller sur `/audit` pour ce site → vérifier que les métriques GA4/GSC ne
   sont plus les données mock (`degraded` doit être absent/`false` si la
   propriété a du vrai trafic).
4. Se connecter avec un compte n'ayant pas le rôle `owner` sur ce
   workspace → vérifier que les actions connecter/changer/déconnecter sont
   invisibles ou désactivées sur `/connections`.
5. "Déconnecter" la connexion → vérifier qu'elle disparaît/passe en statut
   revoked dans l'UI, que le site repasse en dégradation propre sur
   `/audit` (pas de crash).

- [ ] **Step 4 : Rapport**

Résumer à l'utilisateur : nombre de tests, résultat build/lint, résultat
du smoke test manuel, rappel explicite que GTM (lecture et écriture) reste
hors périmètre et documenté comme décision séparée à reprendre
explicitement si un besoin réel apparaît un jour.
