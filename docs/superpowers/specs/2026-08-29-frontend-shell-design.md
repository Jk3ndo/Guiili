# Frontend — Design System + Layout Shell (design validé)

**Date :** 2026-08-29 · **Statut :** validé, en implémentation (branche `feat/frontend-shell`)
**Contexte :** backend OAuth en pause. Ce livrable = le shell UI + design system, sur données mockées typées, prêt à brancher sur l'API plus tard.

## Cible de finition

Knock.app / Novu.co / n8n : dark, dense B2B SaaS, bordures en cheveu, accents indigo/cyan **parcimonieux** (bouton primaire, indicateur d'onglet actif, focus ring, états sélection/hover, points de statut — jamais en aplat large).

## Stack

- **Tailwind v4** — `@import "tailwindcss"` + `@tailwindcss/postcss`, tokens en `@theme` (`app/globals.css`). Pas de `tailwind.config.js`.
- **shadcn/ui** style `new-york`, `cssVariables: true`, icônes lucide → `components/ui/`.
- **next-themes** — `attribute="class"`, `defaultTheme="dark"`, `enableSystem={false}`.
- **cmdk** (via shadcn `command` + `dialog`), **lucide-react**, **geist** (Geist Sans + Geist Mono).
- `prettier` + `prettier-plugin-tailwindcss`.
- État shell : React Context maison (`lib/shell/shell-context.tsx`), collapse persisté en `localStorage`.
- **Pas de tests unitaires** (décision utilisateur). Garantie de non-régression = `next build` + `eslint`. Playwright E2E plus tard.

## Design tokens

Deux couches : **primitives** dans `@theme` (palette brute, familles de police, échelle dense, radii) ; **sémantiques** en CSS vars sur `:root` (dark = défaut), sur lesquelles les vars shadcn (`--background`, `--border`, `--primary`, `--sidebar-*`, `--ring`…) sont mappées.

| token sémantique | valeur |
|---|---|
| `--surface-canvas` | `#0B0F17` |
| `--surface-card` | `#111726` |
| `--surface-raised` (popover, dialog, dropdown) | `#151C2E` |
| `--border-subtle` | `rgba(255,255,255,0.08)` |
| `--border-strong` (hover/active) | `rgba(255,255,255,0.14)` |
| `--text-primary` | `rgba(255,255,255,0.92)` |
| `--text-muted` | `rgba(255,255,255,0.55)` |
| `--text-faint` (labels 12px) | `rgba(255,255,255,0.40)` |
| `--accent-indigo` | `#6366F1` |
| `--accent-cyan` | `#06B6D4` |
| `--status-ok` / `--status-warn` / `--status-danger` | `#22C55E` / `#F59E0B` / `#EF4444` |

**Type scale (dense) :** `--text-xs 12px` (labels muted), `--text-sm 13px` (corps défaut), `--text-base 14px` (corps emphase), `--text-lg 16px`, `--text-xl 20px` (titres de page), `--text-2xl 24px`. Interlignes `1.4`–`1.5`. Données numériques : Geist Mono + `font-variant-numeric: tabular-nums`.

**Radii :** `--radius-sm 6px`, `--radius-md 8px` (cartes, inputs), `--radius-lg 12px` (dialogs).

## Architecture

```
app/
  layout.tsx                <html class="dark"> + fonts geist + <Providers>
  providers.tsx             ThemeProvider (next-themes)
  (shell)/
    layout.tsx              <ShellProvider> + <AppSidebar> + <Topbar> + <main><PageShell>
    page.tsx                redirect → /overview
    overview/page.tsx       header + skeletons (KPIs + zone graphe)
    audit/page.tsx          header + skeletons (table de métriques)
    gtm-export/page.tsx     header + skeletons (liste de snippets + carte export)
    backlog/page.tsx        header + skeletons (colonnes de correctifs)
    connections/page.tsx    header + skeletons (cartes de comptes Google)
components/shell/
  app-sidebar.tsx           shadcn <Sidebar collapsible="icon">
  workspace-switcher.tsx    <DropdownMenu>, site courant + pastille de stack
  nav-main.tsx              5 liens, état actif (barre indigo + fond raised)
  token-health.tsx          footer sidebar : point statut + libellé → /connections
  topbar.tsx                SidebarTrigger + Breadcrumb + bouton ⌘K + "Lancer un diagnostic"
  breadcrumb.tsx            dérivé de usePathname via routes.ts
  command-menu.tsx          cmdk dialog, listener global ⌘K / Ctrl+K
  page-shell.tsx            header (titre, sous-titre, actions) + rythme de padding
components/ui/              shadcn : button sidebar dropdown-menu command dialog
                            breadcrumb badge skeleton tooltip separator scroll-area
                            sheet input kbd
lib/
  utils.ts                 cn()
  shell/shell-context.tsx  { sidebarCollapsed, setSidebarCollapsed (localStorage), activeWorkspaceId, setActiveWorkspace }
  shell/routes.ts          Route[] : href, label, breadcrumbLabel, icon
  mock/types.ts            Workspace, TokenStatus, StackId
  mock/workspaces.ts       Workspace[] mock (3-4 sites, stacks variées, statuts variés)
```

## Navigation (5 sections)

| href | label | icône lucide |
|---|---|---|
| `/overview` | Vue d'ensemble | `LayoutDashboard` |
| `/audit` | Audit & Métriques | `Gauge` |
| `/gtm-export` | Export GTM & Snippets | `FileCode2` |
| `/backlog` | Backlog Correctifs | `ListChecks` |
| `/connections` | Connexions Google | `Plug` |

## Composants clés

- **Sidebar** `collapsible="icon"` : rail 48px ↔ ~260px, état persisté. Haut = `WorkspaceSwitcher`. Milieu = `NavMain` (actif : barre indigo 2px à gauche + fond `--surface-raised` + texte primary ; inactif : texte muted → primary au hover). Bas = `TokenHealth`.
- **WorkspaceSwitcher** : `DropdownMenu` — trigger = nom du site + `<Badge>` de stack (Next.js → indigo tenue, WordPress → neutre, Angular → rouge tenu, Vue → vert tenu, Autre → gris). Items = autres sites + « Ajouter un site » (désactivé, tooltip « bientôt »).
- **TokenHealth** : `<StatusDot status>` + libellé. `ok` → point vert plein, « Connecté ». `needs_reauth` → point ambre + halo pulsé (`animation: pulse`, coupé par `prefers-reduced-motion`), « Reauth requise ». Toute la ligne est un lien vers `/connections`.
- **Topbar** 52px, `border-b` subtle : gauche `SidebarTrigger` + `Breadcrumb` ; droite pilule `⌘K` (ouvre la palette) + `<Button>` primaire « Lancer un diagnostic » (indigo, icône `Play`).
- **CommandMenu** : `CommandDialog`. Groupes — *Aller à* (5 sections), *Actions* (« Lancer un diagnostic », « Changer d'espace », « Voir les connexions Google »), *Espaces* (chaque workspace mock). Raccourci global `⌘K` / `Ctrl+K` (+ `/` optionnel). `Esc` ferme.
- **PageShell** : `<header>` (titre `--text-xl`, sous-titre `--text-sm --text-muted`, slot actions à droite) + `<div>` contenu avec padding constant (`px-6 py-5`, `max-w-[1400px]`).

## Zéro layout shift

- Skeletons aux **dimensions finales exactes** : hauteurs fixes sur les cartes KPI (`h-[92px]`), `aspect-[16/7]` sur les zones de graphe, `min-h` + lignes fixes sur les tables.
- Sidebar + Topbar = **server components statiques** (les parties interactives — triggers, dropdowns — sont des îlots `"use client"`).
- Fonts `next/font` (geist) `display: "swap"` + `adjustFontFallback`.
- Largeur sidebar réservée : le `(shell)/layout.tsx` pose `grid-template-columns: var(--sidebar-width) 1fr` ; le collapse anime `--sidebar-width` (transition `width 200ms ease`), le contenu ne reflow pas.
- `prefers-reduced-motion` : coupe les transitions non essentielles + le pulse du TokenHealth.

## Hors périmètre

Pas d'appel API / auth / lib de graphes / peaufinage thème clair. Responsive : sidebar → `Sheet` sous `md` (fourni par shadcn). Les 5 pages = `PageShell` + skeletons uniquement.

## Critère de fin

`cd frontend && npm run lint && npm run build` → **0 erreur, 0 warning**. Rendu vérifié dans le navigateur.
