import type { Metadata } from "next";

import { GtmExportView } from "@/components/gtm-export/gtm-export-view";
import { getHighlightedSnippets } from "@/lib/gtm/highlight";

export const metadata: Metadata = { title: "Export GTM & Snippets" };

export default async function GtmExportPage() {
  const highlighted = await getHighlightedSnippets();
  return <GtmExportView highlighted={highlighted} />;
}
