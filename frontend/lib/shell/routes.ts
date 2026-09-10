import {
  FileCode2,
  Gauge,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  Plug,
  type LucideIcon,
} from "lucide-react";

export interface AppRoute {
  href: string;
  /** Sidebar + command-palette label. */
  label: string;
  /** Breadcrumb label (usually the same, kept separate on purpose). */
  crumb: string;
  icon: LucideIcon;
}

export const NAV_ROUTES: AppRoute[] = [
  {
    href: "/overview",
    label: "Vue d'ensemble",
    crumb: "Vue d'ensemble",
    icon: LayoutDashboard,
  },
  {
    href: "/audit",
    label: "Audit & Métriques",
    crumb: "Audit & Métriques",
    icon: Gauge,
  },
  {
    href: "/gtm-export",
    label: "Export GTM & Snippets",
    crumb: "Export GTM & Snippets",
    icon: FileCode2,
  },
  {
    href: "/backlog",
    label: "Backlog Correctifs",
    crumb: "Backlog Correctifs",
    icon: ListChecks,
  },
  {
    href: "/conseiller",
    label: "Conseiller",
    crumb: "Conseiller",
    icon: MessageSquareText,
  },
  {
    href: "/connections",
    label: "Connexions Google",
    crumb: "Connexions Google",
    icon: Plug,
  },
];

export function routeForPath(pathname: string): AppRoute | undefined {
  return NAV_ROUTES.find(
    (r) => pathname === r.href || pathname.startsWith(`${r.href}/`),
  );
}
