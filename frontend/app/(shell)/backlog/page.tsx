import type { Metadata } from "next";

import { BacklogView } from "@/components/backlog/backlog-view";
import { getHighlightedFixes } from "@/lib/backlog/highlight";

export const metadata: Metadata = { title: "Backlog Correctifs" };

export default async function BacklogPage() {
  const highlighted = await getHighlightedFixes();
  return <BacklogView highlighted={highlighted} />;
}
