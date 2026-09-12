# Authentification multi-provider, workspaces & connexion Google réelle (design validé)

**Date :** 2026-09-12 · **Statut :** validé en discussion, prêt pour le plan d'implémentation
**Contexte :** le backend OAuth Google (P0) est mergé et fonctionne (`/auth/google/start`,
`/auth/google/callback`, `GET /google/resources`, `POST /link-resource`) mais n'a **aucune UI**
côté frontend — `/connections` est encore 100% mock. Dans le même temps, l'app n'a **aucun
mécanisme de login réel** : le seul moyen d'obtenir une session est `/dev/workspaces`, qui répond
404 dès que `GOOGLE_OAUTH_MOCK=false`. Ce document couvre la reconstruction de ces deux manques
ensemble, plus l'introduction d'un modèle de comptes partagés (workspaces) requis pour permettre
à un utilisateur d'inviter quelqu'un dans son espace.

**Décision de périmètre actée en discussion :** GitHub OAuth est **explicitement hors périmètre**
de ce chantier — reporté à une phase 2 séparée. Ce chantier couvre : login Google (identité
seule), login email/mot de passe, workspaces + invitations, et la connexion Google explicite pour
les données GA4/GSC.

---

## 1. Objectif

Permettre à un vrai utilisateur (pas seulement le dev via un seed mock) de :

1. Créer un compte et se connecter, via **email + mot de passe** ou **Google OAuth**.
2. Disposer automatiquement de son **propre workspace** à l'inscription — comportement inchangé
   pour quelqu'un qui n'invite jamais personne (aujourd'hui : 1 user → N sites ; demain :
   1 workspace, créé pour lui, → N sites).
3. **Inviter une autre personne** dans son workspace (email → lien d'invitation → elle rejoint
   l'espace, avec accès complet à tout ce qu'il contient).
4. **Connecter un compte Google pour les données GA4/GSC** de son workspace, séparément de son
   login — action explicite depuis `/connections`, jamais implicite.
5. Voir et gérer, depuis `/connections`, les connexions Google du workspace et les ressources
   (propriétés GA4, conteneurs GTM, sites GSC) liées à chaque site suivi.

## 2. Principes directeurs (décidés en discussion)

- **Une seule méthode de connexion par compte.** Pas de fusion automatique par email : si un
  email existe déjà via mot de passe et qu'on tente un login Google dessus (ou l'inverse), erreur
  claire — jamais de merge silencieux (surface d'attaque connue : un attaquant pourrait créer un
  compte mot de passe avec l'email de la victime avant qu'elle utilise "Se connecter avec
  Google").
- **Login ≠ connexion de données.** Le login Google ne demande que l'identité
  (`openid email profile`). La connexion Google pour GA4/GSC est une action séparée, déclenchée
  depuis `/connections`, qui demande `analytics.readonly` + `webmasters.readonly`. Les deux ne
  partagent aucun scope, aucun endpoint, aucune ligne de code de flow.
- **Connexions Google partagées au niveau du workspace, pas de l'utilisateur.** Les sites d'un
  workspace utilisent déjà des connexions Google précises ; si chaque membre pouvait ajouter/
  changer ces connexions indépendamment, la source de vérité des données GA4/GSC deviendrait
  ambiguë. Une seule connexion par ressource, gérée explicitement, peu importe qui se logue
  ensuite.
- **Pas de partage site-par-site en v1.** Si tu es membre d'un workspace, tu vois tout ce qu'il
  contient. Pas de rôles granulaires au-delà de `owner`/`member`. YAGNI — à complexifier plus
  tard seulement si le besoin réel apparaît.
- **Plafonds de coût au niveau du workspace, pas de l'utilisateur.** `advisor_usage` (cap
  quotidien de briefs/messages) doit être scopé par workspace : sinon 3 membres actifs
  consomment chacun leur propre plafond, soit 3× le budget prévu pour un seul espace.

## 3. Modèle de données

### 3.1 Tables nouvelles

```python
class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # RESTRICT : on ne supprime jamais un user qui possède encore un workspace ;
    # il faut d'abord transferer la propriete ou supprimer le workspace.


class WorkspaceMember(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "owner" | "member"
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkspaceInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_invitations"
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_email: Mapped[str] = mapped_column(String(320), nullable=False)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # "pending" | "accepted" | "revoked" | "expired"
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "password_reset_tokens"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

`role` et `status` en `String` simple, pas `pg_enum` — même convention que
`AdvisorThread.role`/`AdvisorMessage.status` (incrément 2 du conseiller) : valeurs 100%
contrôlées par le code, évite la danse CHECK-constraint pour un enum qui ne vit que dans
l'application.

Les deux `token` (`WorkspaceInvitation` et `PasswordResetToken`) sont générés via
`secrets.token_urlsafe(32)`, jamais devinables, comparés en base par valeur exacte (index
unique) — pas besoin de hashage, chacun est à usage unique et expire. Seule la durée diffère :
**7 jours** pour une invitation (`WorkspaceInvitation.expires_at`), **1 heure** pour un reset de
mot de passe (`PasswordResetToken.expires_at`, fenêtre courte car action sensible).

### 3.2 Tables existantes modifiées

- **`users`** : `google_sub` devient `nullable=True` (Postgres autorise plusieurs `NULL` sur une
  colonne unique — pas de conflit entre deux comptes email/mot de passe). Nouvelle colonne
  `password_hash: str | None` (nullable — un compte Google pur n'en a pas). Le champ
  `auth_provider` existant est conservé tel quel à titre informatif (dernière méthode utilisée)
  mais n'est **pas** la source de vérité : la logique de login teste directement la présence de
  `password_hash` ou `google_sub`.
- **`websites`** : `user_id` → `workspace_id` (FK `workspaces.id`, `ondelete=CASCADE`).
  `UniqueConstraint("user_id", "domain")` → `UniqueConstraint("workspace_id", "domain")`.
- **`google_connections`** : `user_id` → `workspace_id`. `UniqueConstraint("user_id",
  "google_sub")` → `UniqueConstraint("workspace_id", "google_sub")`.
- **`advisor_usage`** : `user_id` (PK composite avec `day`) → `workspace_id`.
- **Inchangés, décision explicite** : `advisor_threads`/`advisor_messages`/`advisor_tool_calls`
  (déjà scopés via `website_id`, transitivement workspace), `user_advisor_settings` (préférence
  **personnelle** — persona/prompt custom, chacun garde le sien même dans un workspace partagé),
  `audit_log` (`user_id` reste l'acteur qui a fait l'action — pas touché).
- **`oauth_states`** : `user_id` (optionnel) reste tel quel (lié à une tentative de login
  transitoire). Gagne une colonne `workspace_id: UUID | None` (nouvelle, nullable, FK
  `workspaces.id` ondelete CASCADE) — utilisée uniquement par le flow de connexion de données
  (§7) pour retenir quel workspace a initié la demande ; toujours `NULL` pour un flow de login.

### 3.3 Migration de données

Une migration hand-codée (comme `0c6d572e41fe` pour les enums stack_kind) :
1. `CREATE TABLE workspaces/workspace_members/workspace_invitations`.
2. Pour chaque `user` existant : `INSERT INTO workspaces (name, owner_user_id) VALUES
   (<display_name ou email>, user.id)` puis `INSERT INTO workspace_members (workspace_id,
   user_id, role) VALUES (<nouveau workspace>, user.id, 'owner')` — un workspace par user
   existant, lui-même comme owner.
3. `ALTER TABLE websites ADD COLUMN workspace_id`, backfill depuis le mapping user→workspace créé
   à l'étape 2, puis `NOT NULL` + `DROP COLUMN user_id` + recréer la contrainte unique.
4. Même chose pour `google_connections` et `advisor_usage`.
5. `ALTER TABLE users ALTER COLUMN google_sub DROP NOT NULL`, `ADD COLUMN password_hash`.

Given qu'il n'y a aujourd'hui que le seed dev (`/dev/workspaces`) en pratique, cette migration de
données n'a réellement qu'un jeu de données de test à backfiller — mais elle doit être écrite
correctement pour ne pas casser un environnement où de vrais comptes existeraient déjà.

## 4. Authentification

### 4.1 Email + mot de passe

- `argon2-cffi` pour le hash (recommandation actuelle — `passlib` n'est plus activement
  maintenu). Un module `app/security/password.py` : `hash_password(plain) -> str`,
  `verify_password(plain, hash) -> bool`.
- `POST /auth/register {email, password, display_name}` :
  - Email déjà utilisé (peu importe la méthode) → `409` avec message explicite selon le cas
    (`"ce compte utilise déjà Google, connecte-toi avec Google"` vs `"email déjà utilisé"`).
  - Sinon : crée `User(email, password_hash, google_sub=None)`, crée son `Workspace` +
    `WorkspaceMember(role="owner")`, pose le cookie de session (même `issue_session` existant),
    `201`.
- `POST /auth/login {email, password}` : cherche le `User` par email ; si `password_hash is
  None` (compte Google pur) → `400` explicite ("ce compte utilise Google, pas de mot de passe") ;
  sinon vérifie le hash, pose le cookie, `200`.
- `POST /auth/logout` : supprime le cookie de session (`response.delete_cookie(...)`) — **n'existe
  pas aujourd'hui**, à ajouter (jusqu'ici, seul le dev-login existait, sans logout).
- Pas de vérification d'email en v1 (YAGNI — accepté comme limite temporaire, noté en risque
  §9).

### 4.2 Réinitialisation de mot de passe

- `POST /auth/password-reset/request {email}` : si un compte mot de passe existe pour cet email,
  crée une ligne `PasswordResetToken` (§3.1, expiration 1h), envoie l'email via `EmailSender`
  (§6). Répond toujours `200` que le compte existe ou non (ne pas révéler quels emails sont
  inscrits).
- `POST /auth/password-reset/confirm {token, new_password}` : valide le token (non expiré, non
  utilisé), met à jour `password_hash`, marque le token utilisé.

### 4.3 Login Google (identité seule)

- `GET /auth/google/start` **change de comportement** : ne demande plus le bundle complet
  `GOOGLE_OAUTH_SCOPES` mais un nouveau tuple `GOOGLE_LOGIN_SCOPES = ("openid", "email",
  "profile")`. Le callback (`/auth/google/callback`) ne fait **plus** `upsert_google_connection`
  automatiquement — il crée/authentifie uniquement le `User` (+ son workspace si nouveau compte)
  et pose le cookie.
- Si `consumed.user_id is None` (flow de login pur) et qu'aucun `User` n'a ce `google_sub` : même
  garde-fou qu'en 4.1 — si l'email existe déjà via mot de passe, `400` explicite plutôt que
  fusion silencieuse.
- **Breaking change assumé** sur `auth.py` et `google_oauth/real.py` (scope paramétrable) : tests
  existants sur le callback à adapter (voir §8).

## 5. Workspaces & invitations

- `GET /workspaces/mine` : liste des workspaces dont l'utilisateur courant est membre (avec son
  rôle dans chacun).
- `POST /workspaces/{id}/invitations {invited_email}` : réservé au `owner` du workspace ; crée
  l'invitation (token, expiration 7 jours), envoie l'email via `EmailSender`.
- `GET /invitations/{token}` : renvoie l'état de l'invitation (workspace name, email invité,
  valide/expirée/déjà utilisée) — pour que le frontend affiche la bonne page avant que
  l'utilisateur choisisse de s'inscrire ou se connecter.
- `POST /invitations/{token}/accept` : si l'utilisateur courant n'est pas connecté, doit d'abord
  passer par `/auth/register` ou `/auth/login` (le frontend enchaîne automatiquement) ; une fois
  connecté, si `current_user.email == invitation.invited_email` (sinon `403` — l'invitation est
  nominative), crée `WorkspaceMember(role="member")`, marque l'invitation `accepted`.
- `DELETE /workspaces/{id}/members/{user_id}` : réservé au `owner`, retire un membre (ne peut pas
  se retirer lui-même — pas de workspace sans owner en v1 ; transfert de propriété hors
  périmètre).
- **`GET /websites` évolue** : renvoie les sites de **tous les workspaces** dont l'utilisateur est
  membre (liste plate) — pas de sélecteur de workspace explicite en v1. Si quelqu'un est membre
  de plusieurs workspaces avec des domaines qui se chevauchent, cas limite accepté, non bloquant
  (voir §9).
- `_owned_website` (et équivalents dans tous les endpoints) passe de `site.user_id != user.id` à
  une vérification d'appartenance : `site.workspace_id` doit être dans les workspaces dont
  `user.id` est membre (`workspace_members`).

## 6. Envoi d'email — interface abstraite

Même pattern que `AuditProbe`/`GoogleOAuthClient` (ABC + Mock + Real, injectée via
`app/api/deps.py`) :

```python
class EmailSender(ABC):
    async def send(self, *, to: str, subject: str, body_text: str) -> None: ...

class ConsoleEmailSender(EmailSender):
    """Dev : logue le contenu (avec le lien) au lieu d'envoyer. Jamais de vrai reseau."""
    async def send(self, *, to: str, subject: str, body_text: str) -> None:
        logger.info("EMAIL (console) to=%s subject=%s\n%s", to, subject, body_text)
```

`RealEmailSender` **non implémentée dans ce chantier** — le choix de fournisseur (Resend, SES,
Postmark...) est explicitement différé. `get_email_sender()` renvoie `ConsoleEmailSender` tant
qu'aucune config de fournisseur n'est présente ; lève une erreur claire si un jour on force le
mode réel sans config plutôt que d'échouer silencieusement.

## 7. Connexion Google pour données GA4/GSC (le chantier d'origine)

- Nouvel endpoint distinct : `GET /connections/google/start` (nom différent de
  `/auth/google/start` pour ne jamais les confondre) — requiert une session active
  (`CurrentUserDep`), scopes = `GOOGLE_DATA_SCOPES = ("openid", "email", "analytics.readonly",
  "webmasters.readonly")`, `redirect_to` fixé sur `/connections`.
- `GET /connections/google/callback` : consomme le state, échange le code, upsert
  `GoogleConnection` **scopée sur `current_workspace_id`** (pas sur l'utilisateur qui clique) —
  nécessite de faire transiter le workspace actif dans le state OAuth (colonne
  `oauth_states.workspace_id`, nouvelle, nullable).
- Frontend `/connections` (remplace `connections-view.tsx` mock) :
  - Section identités : `GET /google/resources` (déjà existant) → cartes connexion (email,
    statut actif/needs_reauth), bouton "Ajouter une connexion" → redirige vers
    `/connections/google/start`, bouton "Déconnecter" (nouveau `DELETE
    /connections/{id}` — à ajouter, absent aujourd'hui).
  - Section ressources : pour le site actif, dropdown GA4/GTM/GSC alimenté par
    `GET /google/resources`, sélection → `POST /websites/{id}/link-resource` (déjà existant).
  - Bannière "reauth requise" si `status == needs_reauth`.

## 8. Tests

- `test_auth_password.py` (nouveau) : register (succès, email dupliqué mot de passe, email
  dupliqué Google), login (succès, mauvais mot de passe, compte Google sans password), reset
  (token valide/expiré/déjà utilisé), logout.
- `test_auth_google_login.py` (adapté depuis les tests OAuth existants) : login scope
  identité-seule, pas de `GoogleConnection` créée automatiquement, garde-fou email dupliqué.
- `test_workspaces.py` (nouveau) : création auto à l'inscription, invitation (créer, lister,
  accepter, refuser un email non-matchant, expirée), retrait de membre, `owner` ne peut pas se
  retirer lui-même.
- `test_google_connections_data.py` (nouveau) : flow `/connections/google/start` +
  `/connections/google/callback`, connexion scopée workspace, deux membres du même workspace
  voient la même connexion.
- Migration : `test_migrations.py` + `test_enum_check_constraints.py` étendus si nécessaire
  (`role`/`status` en `String`, pas de CHECK à garder synchronisé — pas de garde-fou enum requis
  ici, contrairement à `pg_enum`).
- Tous les tests existants qui construisent un `Website`/`GoogleConnection` directement (fixtures
  `_website`, `_site`, etc. dans `test_audit_endpoints.py`, `test_advisor_*.py`,
  `test_websites.py`...) doivent créer un `Workspace` + `WorkspaceMember` au lieu de passer
  `user_id` — **impact large sur les fixtures existantes**, à traiter méthodiquement tâche par
  tâche du plan.

## 9. Hors périmètre (explicite)

- **GitHub OAuth** — phase 2 séparée, décidée en discussion.
- **Fournisseur d'email réel** — `ConsoleEmailSender` seulement ; brancher Resend/SES/Postmark
  est un chantier séparé, déclenché quand un choix de fournisseur est fait.
- **Partage site-par-site** ou rôles au-delà de `owner`/`member` — tout membre voit tout le
  workspace.
- **Transfert de propriété d'un workspace** (changer qui est `owner`) — pas de flow prévu ; un
  owner ne peut pas être retiré, un cas limite à traiter si le besoin apparaît.
- **Vérification d'email à l'inscription** — un compte email/mot de passe est utilisable
  immédiatement, sans confirmation. Accepté comme limite temporaire.
- **Sélecteur de workspace explicite côté UI** — `GET /websites` renvoie tout, à plat ; si
  chevauchement de domaines entre deux workspaces d'un même user, comportement non spécifié
  (cas limite, pas bloquant pour le lancement).
- **Politique de confidentialité + vérification de marque Google (P3)** — dépend des décisions de
  ce document (quelles données, quels scopes, quel partage) mais rédigée séparément, après ce
  chantier.

## 10. Risques & questions ouvertes

1. **Pas de vérification d'email** : un compte peut être créé avec un email qu'on ne possède pas
   ; limite acceptée pour ce chantier, à revisiter si abus constaté.
2. **`advisor_usage` par workspace** change le sens du plafond quotidien existant (actuellement
   par user) — à documenter clairement dans le changelog utilisateur si des beta-testeurs
   existent déjà.
3. **Impact fixtures de test large** (§8, dernier point) — risque principal d'estimation du plan :
   probablement le poste le plus long du chantier, pas la logique métier elle-même.
4. **`oauth_states.workspace_id`** (§7) : nécessite de connaître le workspace actif au moment de
   déclencher `/connections/google/start` — le frontend doit le transmettre explicitement (query
   param ou dérivé du site actif côté serveur via `CurrentUserDep` + son unique/premier
   workspace tant qu'il n'y a pas de sélecteur explicite, cf. §9).
5. **P3** (privacy policy, vérification Google) — à traiter dans un document séparé une fois ce
   chantier stabilisé, en s'appuyant sur les scopes/flows définis ici.
