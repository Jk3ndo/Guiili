# Connexion Google pour les données (GA4/GSC) — spec

**Décisions de périmètre actées en discussion :**
- **Réutilisation maximale de l'existant** — la découverte de ressources
  (`GET /google/resources`), la liaison site↔ressource
  (`POST /websites/{id}/link-resource`) et leur consommation dans
  `RealAuditProbe` sont déjà construites, déjà scopées workspace, et ne
  changent pas dans ce chantier. Seuls le flow OAuth d'entrée/sortie et la
  vraie UI `/connections` (100 % mock aujourd'hui) manquent.
- **Google Tag Manager explicitement hors périmètre** — aucune fonctionnalité
  livrée à ce jour (export GTM, check statique, vérification headless)
  n'appelle l'API Tag Manager ; toutes travaillent directement sur la page
  rendue. Pas de scope `tagmanager.readonly` demandé, pas de section GTM
  dans la vraie UI. La lecture *et l'écriture* de configuration GTM via
  l'API a été explicitement écartée de ce chantier (scopes sensibles
  nécessitant une vérification Google renforcée, risque de casser le
  tracking ou le site en cas d'écriture malformée, changement de
  philosophie pour un produit conçu comme lecture seule depuis l'origine) —
  à retraiter comme décision séparée et explicite si un jour un vrai
  besoin apparaît.
- **Réservé au propriétaire du workspace** — connecter un nouveau compte
  Google, changer l'assignation d'une ressource, déconnecter un compte :
  ces trois actions sont réservées à `role == "owner"`, même garde que les
  invitations et le retrait de membre.
- **Connexions partagées au niveau workspace** — décidé pendant le
  brainstorming de la spec auth/workspaces (§2), confirmé ici : tous les
  membres du workspace voient et utilisent les mêmes connexions Google, pas
  de partage par site.

---

## 1. Objectif

Permettre au propriétaire d'un workspace de connecter un ou plusieurs vrais
comptes Google (scopes lecture seule GA4/GSC), et d'assigner à chaque site
suivi la ressource (propriété GA4, propriété Search Console) réellement
utilisée pour son marketing — remplaçant la simulation 100 % mock de
`/connections` par des données réelles, sans toucher au login (déjà
fonctionnel, spec du 2026-09-12) ni au moteur d'audit (`RealAuditProbe`,
déjà prêt à consommer ces connexions).

## 2. Ce qui existe déjà (vérifié dans le code, ne change pas)

- **Modèle de données** : `GoogleConnection` (workspace_id, google_sub,
  google_account_email, granted_scopes, refresh_token_encrypted,
  encryption_key_version, status: `active`/`needs_reauth`/`revoked`) et
  `WebsiteGoogleLink` (website_id, google_connection_id, resource_type:
  `ga4_property`/`gtm_container`/`gsc_site`, resource_id,
  resource_display_name) — `google_connections.py` /
  `website_google_link.py`. FK `WebsiteGoogleLink.google_connection_id`
  en `ondelete=CASCADE`.
- **Chiffrement** : `app/services/connections.py` —
  `connection_aad(workspace_id, google_sub)` lie cryptographiquement le
  blob chiffré au couple (workspace, identité Google) ;
  `upsert_google_connection(session, *, workspace_id, userinfo, token,
  cipher)` crée ou met à jour la ligne (upsert par `(workspace_id,
  google_sub)`, idempotent sur reconnexion du même compte) ;
  `decrypt_refresh_token(connection, *, cipher)`.
- **`GET /google/resources`** (`app/api/v1/endpoints/google.py`) : agrège
  les connexions du workspace de l'utilisateur, rafraîchit chaque token
  actif, `invalid_grant` → passe la connexion en `needs_reauth`, découvre
  GA4/GTM/GSC via `RealGoogleOAuthClient.discover_resources` (GTM restera
  vide sans le scope, sans erreur — `discover_resources` appelle les 3 API
  sans lever d'exception sur un 403, cf. `real.py::_discover_gtm`, qui lit
  juste `.get("account", [])` sur le payload d'erreur).
- **`POST /websites/{id}/link-resource`** : lie une ressource découverte à
  un site (une seule ressource par `(site, type)`, la nouvelle liaison
  remplace l'ancienne), vérifie l'appartenance du site et de la connexion
  au(x) workspace(s) de l'utilisateur.
- **`RealAuditProbe._google_signals`** (`app/services/audit_probe.py`) :
  résout `website_google_links` ⋈ `google_connections` par `website_id`
  directement (pas besoin de repasser par workspace_id ici), dégrade
  proprement (`score=0, degraded=True`) si le token est absent/invalide —
  `_access_token` ne tente un rafraîchissement que si
  `connection.status == ConnectionStatus.ACTIVE` ; `needs_reauth` et
  **`revoked` sont déjà traités identiquement** (aucun changement requis
  pour supporter la déconnexion, voir §3.3).
- **`RealGoogleOAuthClient`** (`app/services/google_oauth/real.py`) : PKCE,
  échange de code, refresh, `fetch_userinfo`, `discover_resources`,
  `revoke(token)` — tous déjà implémentés et fonctionnels (le login les
  utilise déjà pour PKCE/échange/userinfo).
- **`oauth_states`** : colonne `workspace_id` déjà présente en base
  (migration `1d03150b69e5`), **jamais encore lue ni écrite** côté
  application — c'est la pièce manquante précise pour ce chantier.

## 3. Ce qui manque

### 3.0 Prérequis découvert en rédigeant la spec : `workspace_id` absent de `GET /websites`

Vérifié dans le code (pas une supposition) : ni `WebsiteOut`
(`app/api/v1/endpoints/websites.py`) ni le DTO frontend correspondant
(`WebsiteDto`, `lib/api/dto.ts`) n'exposent `workspace_id`. Sans ce champ,
le frontend n'a **aucun moyen de savoir** à quel workspace réel appartient
le site actuellement sélectionné dans le shell — donc aucun moyen de
construire l'appel `GET /connections/google/start?workspace_id=...`, ni de
déterminer si l'utilisateur courant est `owner` de CE workspace (en
croisant avec `GET /workspaces/mine`, qui renvoie déjà `[{id, name,
role}]`) pour afficher ou masquer les actions réservées au propriétaire.

**⚠️ Piège terminologique à noter pour qui lit le code frontend** : le
type frontend nommé `Workspace` (`lib/mock/types.ts`, "workspace switcher"
dans la sidebar) désigne en réalité un **site suivi** — un reliquat du nom
donné avant que le vrai modèle multi-tenant (`Workspace` côté backend,
groupe utilisateurs+sites) n'existe. Les deux notions cohabitent sous le
même mot, dans deux couches différentes, sans lien explicite entre elles
aujourd'hui — précisément le trou que ce paragraphe comble.

Correctif, additif des deux côtés (aucune régression) :
- `WebsiteOut` (backend) : ajouter `workspace_id: UUID`.
- `WebsiteDto` (frontend, `lib/api/dto.ts`) : ajouter `workspace_id: string`.
- `websiteToWorkspace()` (`lib/api/websites.ts`) : reporter ce champ sur le
  type frontend `Workspace` (site) — nouveau champ `realWorkspaceId:
  string` (nom distinct de `id`/`websiteId` existants pour ne pas
  aggraver la confusion terminologique ci-dessus).
- `components/connections/*` calcule `isOwner` en croisant
  `workspace.realWorkspaceId` avec la liste `GET /workspaces/mine`.

### 3.1 Scopes de données

```python
# app/services/google_oauth/base.py
GOOGLE_DATA_SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
)
```
`openid`/`email` nécessaires pour identifier le compte connecté
(`fetch_userinfo`) — sans eux on ne pourrait pas peupler
`google_account_email`/`google_sub` sur `GoogleConnection`.

### 3.2 Transaction OAuth liée à un workspace

`app/services/oauth_state.py` étend ce qui existe (déjà utilisé par le
login, qui continue de passer `workspace_id=None`) :

```python
@dataclass(frozen=True, slots=True)
class OAuthTransaction:
    state: str
    code_challenge: str

@dataclass(frozen=True, slots=True)
class ConsumedOAuthState:
    code_verifier: str
    user_id: UUID | None
    workspace_id: UUID | None   # NOUVEAU
    redirect_to: str | None

async def create_oauth_transaction(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    workspace_id: UUID | None,   # NOUVEAU
    redirect_to: str | None,
    ttl_seconds: int,
) -> OAuthTransaction:
    ...
    session.add(OAuthState(
        state=state, code_verifier=verifier, user_id=user_id,
        workspace_id=workspace_id,   # NOUVEAU
        redirect_to=redirect_to,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    ))
    ...

async def consume_oauth_state(session, state) -> ConsumedOAuthState | None:
    ...
    snapshot = ConsumedOAuthState(
        code_verifier=row.code_verifier,
        user_id=row.user_id,
        workspace_id=row.workspace_id,   # NOUVEAU
        redirect_to=row.redirect_to,
    )
    ...
```
Le login (`/auth/google/start`/`callback`) continue d'appeler ces fonctions
avec `workspace_id=None` — changement additif, aucune régression attendue,
mais les deux call sites du login sont à mettre à jour pour passer le
nouveau paramètre nommé explicitement (`workspace_id=None`).

### 3.3 Endpoints — `app/api/v1/endpoints/connections.py` (nouveau fichier)

```python
router = APIRouter(prefix="/connections", tags=["connections"])

class ConnectionStartResponse(BaseModel):
    authorization_url: str

@router.get("/google/start", response_model=ConnectionStartResponse)
async def connections_google_start(
    workspace_id: UUID,  # query param (GET, pas dans le path) : ?workspace_id=...
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    client: GoogleClientDep,
) -> ConnectionStartResponse:
    await require_owner(session, workspace_id=workspace_id, user_id=user.id)
    transaction = await create_oauth_transaction(
        session, user_id=user.id, workspace_id=workspace_id,
        redirect_to="/connections", ttl_seconds=settings.oauth_state_ttl_seconds,
    )
    await session.commit()
    url = client.build_authorization_url(
        state=transaction.state, code_challenge=transaction.code_challenge,
        scopes=GOOGLE_DATA_SCOPES,
    )
    return ConnectionStartResponse(authorization_url=url)


@router.get("/google/callback")
async def connections_google_callback(
    session: SessionDep, settings: SettingsDep, client: GoogleClientDep,
    cipher: TokenCipherDep,
    code: str | None = None, state: str | None = None, error: str | None = None,
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
        # workspace_id absent = transaction de login, pas de donnees —
        # ne devrait jamais arriver via ce chemin, 400 defensif.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="transaction OAuth invalide pour une connexion de donnees",
        )
    try:
        token = await client.exchange_code(code=code, code_verifier=consumed.code_verifier)
    except InvalidGrantError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code d'autorisation invalide",
        ) from None
    if token.refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google n'a pas fourni de refresh token — reconsentement requis",
        )
    userinfo = await client.fetch_userinfo(access_token=token.access_token)
    await upsert_google_connection(
        session, workspace_id=consumed.workspace_id, userinfo=userinfo,
        token=token, cipher=cipher,
    )
    await session.commit()
    return RedirectResponse(
        url=consumed.redirect_to or settings.frontend_base_url,
        status_code=status.HTTP_302_FOUND,
    )


class DisconnectResponse(BaseModel):
    status: str

@router.delete("/{connection_id}", response_model=DisconnectResponse)
async def disconnect_connection(
    connection_id: UUID, user: CurrentUserDep, session: SessionDep,
    client: GoogleClientDep, cipher: TokenCipherDep,
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
        except Exception:  # noqa: BLE001 — best-effort assume, voir note
            pass  # l'intention locale de deconnecter prime sur cet appel
    connection.status = ConnectionStatus.REVOKED
    await session.commit()
    return DisconnectResponse(status="revoked")
```

`_require_owner` (vérifiée dans le code : signature actuelle
`_require_owner(session: SessionDep, workspace_id: UUID, user_id: UUID)`,
un helper **privé** de `app/api/v1/endpoints/workspaces.py`, pas de la
couche services) — à **déplacer** vers `app/services/workspaces.py` en
fonction publique `require_owner(session, *, workspace_id: UUID,
user_id: UUID) -> None` : logique interne inchangée (compose sur
`is_member`, déjà testée), seul le nommage des paramètres passe en
keyword-only (`*,`) pour matcher la convention déjà suivie par
`is_member`/`owned_website` dans ce même module — implique de mettre à
jour les call sites existants dans `workspaces.py` pour passer
`workspace_id=`/`user_id=` explicitement (mécanique, zéro changement de
comportement). `connections.py` importe cette version partagée. Cohérent
avec le pattern déjà suivi pour `is_member`/`owned_website` : toute
logique d'appartenance vit dans `app/services/workspaces.py`, jamais
dupliquée dans un module d'endpoints.

**`except Exception` volontairement large sur l'appel de révocation** —
vérifié dans le code : `RealGoogleOAuthClient.revoke()` (`real.py`) ne lève
jamais `GoogleOAuthError` sur un échec HTTP (il ne vérifie même pas le
code de statut de la réponse) ; seule une erreur réseau brute
(`httpx.ConnectError`/`TimeoutException`, sous-classes de
`httpx.HTTPError`, pas de `GoogleOAuthError`) remonterait. Comme l'appel
est un best-effort pur ("on essaie de prévenir Google, mais l'intention
locale de déconnecter prime toujours"), capter large ici est le choix
correct plutôt que d'énumérer chaque type d'exception réseau possible —
seul cet appel précis est concerné, pas de large `except` ailleurs dans
l'endpoint.

**Déconnexion = révocation douce (`status=REVOKED`), pas de suppression** —
choix délibéré : `ConnectionStatus.REVOKED` existe déjà dans l'enum
précisément pour ça, et `RealAuditProbe._access_token` traite déjà tout
statut non-`ACTIVE` comme "pas de token disponible, dégrader" sans
distinguer `needs_reauth` de `revoked`. Aucune ligne `WebsiteGoogleLink`
n'est supprimée — un site dont la ressource pointe vers une connexion
révoquée dégrade proprement (déjà le comportement existant), et
reconnecter le même compte (`upsert_google_connection`) réactive la ligne
existante (`status=ACTIVE`) sans dupliquer. Mêmes principes que
`DELETE /websites/{id}?purge=bool` (archivage réversible par défaut).

### 3.4 Câblage router

`app/api/v1/router.py` : enregistrer le nouveau router `connections`.

### 3.5 Frontend

- `frontend/lib/api/connections.ts` (nouveau) : `startGoogleConnection(workspaceId)`,
  `listGoogleResources()` (→ `GET /google/resources`, déjà servi),
  `linkResource(websiteId, body)` (→ `POST /websites/{id}/link-resource`,
  déjà servi), `disconnectConnection(connectionId)` (→
  `DELETE /connections/{id}`).
- `frontend/app/connections/google/page.tsx` (nouveau) : page intermédiaire
  identique au pattern de `login/google/page.tsx` (fetch de
  `authorization_url` puis `window.location.href`) — nécessaire pour la
  même raison (l'endpoint renvoie du JSON, pas une redirection HTTP directe).
- `components/connections/*.tsx` (existants, à adapter) : `connections-view.tsx`
  bascule de `lib/mock/connections.ts` vers les vrais appels ci-dessus,
  en résolvant `workspaceId` depuis `workspace.realWorkspaceId` (site
  actuellement sélectionné, §3.0) ; `identities-section.tsx`/`identity-card.tsx`
  affichent les vraies connexions (email, scopes, statut, dernière
  synchro) et le bouton "Connecter un compte Google" (visible seulement si
  `realWorkspaceId` correspond à une entrée `role === "owner"` dans
  `GET /workspaces/mine`) ; `resources-section.tsx`/`resource-row.tsx`
  affichent les ressources découvertes par type (GA4, GSC — **pas de
  section GTM** dans la vraie UI) avec le sélecteur "Changer" déjà
  maquetté, réservé lui aussi au propriétaire.
- Comportement pour un non-propriétaire : la page reste consultable
  (lecture seule) mais les actions (connecter/changer/déconnecter) sont
  masquées ou désactivées — cohérent avec le principe "réservé au
  propriétaire" sans bloquer la visibilité de l'état des connexions aux
  autres membres.

## 4. Tests

- `tests/test_websites.py` : étendre le test existant de `GET /websites`
  pour vérifier que `workspace_id` est bien présent et correct dans la
  réponse (§3.0).
- `tests/test_connections_google_start.py` : garde propriétaire (membre
  simple → 403, non-membre → 404, propriétaire → 200 avec
  `authorization_url` contenant les scopes `analytics.readonly` +
  `webmasters.readonly`, sans `tagmanager`).
- `tests/test_connections_google_callback.py` : création de connexion
  (vérifie `workspace_id`/`google_sub`/`google_account_email` corrects),
  idempotence sur reconnexion du même compte (pas de doublon, `status`
  repasse à `active` si elle était `revoked`), refus consentement
  (`error=...` → 400), state invalide/expiré → 400, refresh_token absent →
  400.
- `tests/test_connections_disconnect.py` : garde propriétaire, `revoke()`
  appelé sur le mock client, `status` passe à `revoked`, aucune ligne
  `WebsiteGoogleLink` supprimée, déconnexion réussit même si `revoke()`
  lève une exception (mock configurable pour simuler l'échec).
- Migration : ajouter `workspace_id` à `OAuthState`/`ConsumedOAuthState`
  n'a **aucun impact schema** (la colonne existe déjà) — pas de nouvelle
  migration Alembic pour ce chantier.
- Tests existants de `/google/resources` et `/link-resource` : aucune
  modification attendue (déjà corrects), à faire tourner pour confirmer
  l'absence de régression.

## 5. Hors périmètre (explicite)

- **Google Tag Manager** (lecture et écriture) — voir décisions de
  périmètre en tête de document.
- **Sélecteur de workspace actif visible dans `/connections`** — la page
  agit sur le workspace actuellement sélectionné dans le shell (cookie
  `cc_workspace`), pas de UI dédiée pour choisir explicitement "pour quel
  workspace je connecte ce compte" au-delà de ce qui existe déjà.
- **Notification aux autres membres** qu'une connexion a été
  ajoutée/révoquée par le propriétaire — hors périmètre, pas demandé.
- **Transfert de propriété d'une connexion** entre workspaces — jamais
  nécessaire (une connexion est liée à un workspace dès sa création,
  immuable).

## 6. Risques

- **`discover_resources` appelle toujours les 3 API (GA4/GTM/GSC)** même
  sans scope GTM — actuellement inoffensif (retour vide, pas d'exception)
  mais fragile si Google change un jour son comportement d'erreur sur 403
  (pourrait lever au lieu de renvoyer un payload vide). Risque mineur,
  déjà présent avant ce chantier (le scope GTM n'a jamais été demandé nulle
  part), non aggravé par ce chantier. Non bloquant, à surveiller si un jour
  GTM revient au périmètre.
- **Revue whole-branch de l'auth a trouvé un bug de callback OAuth
  cross-site** (cookie `SameSite=Lax` entre `vercel.app` et `run.app`,
  corrigé par un proxy Vercel) — ce nouveau callback (`/connections/google/callback`)
  passera par le même proxy et n'a pas ce problème (il ne pose pas de
  nouveau cookie, il ne fait que lire la session existante via
  `CurrentUserDep`, déjà correctement transmise par le proxy).
