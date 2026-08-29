"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  RESOURCE_META,
  type ResourceLink,
  type ResourceType,
} from "@/lib/mock/connections";

import { ResourceRow } from "./resource-row";

export function ResourcesSection({
  siteName,
  resources,
}: {
  siteName: string;
  resources: ResourceLink[];
}) {
  const [links, setLinks] = useState(resources);

  function handleChange(type: ResourceType, id: string) {
    const option = links
      .find((link) => link.type === type)
      ?.options.find((candidate) => candidate.id === id);

    setLinks((prev) =>
      prev.map((link) =>
        link.type === type ? { ...link, linkedId: id } : link,
      ),
    );

    toast("Ressource réassignée", {
      description: `${RESOURCE_META[type].name} → ${option?.label ?? id}`,
    });
  }

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
        {links.map((link) => (
          <ResourceRow key={link.type} link={link} onChange={handleChange} />
        ))}
      </div>
    </section>
  );
}
