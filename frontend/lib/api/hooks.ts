"use client";

import { useCallback, useEffect, useState } from "react";

import { getBacklog, type IssueItem, type IssueStatus } from "@/lib/mock/backlog";
import { getOverview } from "@/lib/mock/overview";
import type { OverviewData, Workspace } from "@/lib/mock/types";

import { runDiagnostic } from "./actions";
import { apiGet, apiPatch } from "./client";
import { notifyDemoMode } from "./demo";
import type { IssueDto, OverviewDto, SnippetsDto } from "./dto";
import { onDiagnosticComplete } from "./events";
import { mapIssue, mapOverview, STATUS_TO_API } from "./mappers";
import { resolveWebsiteId } from "./workspaces";

export type DataSource = "api" | "fallback";

export function useOverview(workspace: Workspace) {
  const [data, setData] = useState<OverviewData>(() => getOverview(workspace));
  const [source, setSource] = useState<DataSource>("fallback");

  const load = useCallback(async () => {
    try {
      const websiteId = await resolveWebsiteId(workspace.domain);
      const dto = await apiGet<OverviewDto>(`/websites/${websiteId}/overview`);
      setData(mapOverview(dto));
      setSource("api");
    } catch {
      notifyDemoMode();
      setData(getOverview(workspace));
      setSource("fallback");
    }
  }, [workspace]);

  useEffect(() => {
    void load();
    return onDiagnosticComplete(() => void load());
  }, [load]);

  const rescan = useCallback(async () => {
    await runDiagnostic(workspace.domain);
    await load();
  }, [workspace.domain, load]);

  return { data, source, rescan };
}

export function useBacklog(workspace: Workspace) {
  const [items, setItems] = useState<IssueItem[]>(() => getBacklog(workspace));
  const [source, setSource] = useState<DataSource>("fallback");
  const [version, setVersion] = useState(0);

  const load = useCallback(async () => {
    try {
      const websiteId = await resolveWebsiteId(workspace.domain);
      const dtos = await apiGet<IssueDto[]>(`/websites/${websiteId}/issues`);
      setItems(dtos.map(mapIssue));
      setSource("api");
    } catch {
      notifyDemoMode();
      setItems(getBacklog(workspace));
      setSource("fallback");
    }
    setVersion((current) => current + 1);
  }, [workspace]);

  useEffect(() => {
    void load();
    return onDiagnosticComplete(() => void load());
  }, [load]);

  const persistStatus = useCallback(
    async (issueId: string, status: IssueStatus) => {
      if (issueId.startsWith("user-")) return; // ticket ajouté localement
      try {
        const websiteId = await resolveWebsiteId(workspace.domain);
        await apiPatch(`/websites/${websiteId}/issues/${issueId}`, {
          status: STATUS_TO_API[status],
        });
      } catch {
        notifyDemoMode();
      }
    },
    [workspace.domain],
  );

  return { items, source, version, persistStatus };
}

export function useSnippets(workspace: Workspace) {
  const [snippets, setSnippets] = useState<SnippetsDto | null>(null);
  const [source, setSource] = useState<DataSource>("fallback");

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const websiteId = await resolveWebsiteId(workspace.domain);
        const dto = await apiGet<SnippetsDto>(
          `/websites/${websiteId}/snippets`,
        );
        if (!active) return;
        setSnippets(dto);
        setSource("api");
      } catch {
        if (!active) return;
        notifyDemoMode();
        setSnippets(null);
        setSource("fallback");
      }
    })();
    return () => {
      active = false;
    };
  }, [workspace.domain]);

  return { snippets, source };
}
