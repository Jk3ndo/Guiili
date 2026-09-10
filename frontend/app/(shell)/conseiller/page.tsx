import type { Metadata } from "next";

import { AdvisorView } from "@/components/conseiller/advisor-view";

export const metadata: Metadata = { title: "Conseiller" };

export default function ConseillerPage() {
  return <AdvisorView />;
}
