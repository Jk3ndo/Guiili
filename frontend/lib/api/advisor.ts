import { apiGet, apiPostSlow, apiPut } from "./client";
import type {
  AdvisorBriefDto,
  AdvisorSettingsDto,
  AdvisorThreadDto,
  AdvisorThreadSummaryDto,
} from "./dto";

export async function fetchAdvisorSettings(): Promise<AdvisorSettingsDto> {
  return apiGet<AdvisorSettingsDto>("/advisor/settings");
}

export async function saveAdvisorSettings(body: {
  persona_key: string;
  custom_prompt: string | null;
}): Promise<AdvisorSettingsDto> {
  return apiPut<AdvisorSettingsDto>("/advisor/settings", body);
}

export async function generateBrief(websiteId: string): Promise<AdvisorBriefDto> {
  return apiPostSlow<AdvisorBriefDto>(
    `/websites/${websiteId}/advisor/brief`,
    undefined,
  );
}

export async function fetchThreads(
  websiteId: string,
): Promise<AdvisorThreadSummaryDto[]> {
  return apiGet<AdvisorThreadSummaryDto[]>(
    `/websites/${websiteId}/advisor/threads`,
  );
}

export async function fetchThread(threadId: string): Promise<AdvisorThreadDto> {
  return apiGet<AdvisorThreadDto>(`/advisor/threads/${threadId}`);
}
