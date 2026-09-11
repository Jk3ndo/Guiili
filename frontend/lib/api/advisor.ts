import { ApiError, API_BASE, apiDelete, apiGet, apiPostSlow, apiPut } from "./client";
import type {
  AdvisorBriefDto,
  AdvisorSettingsDto,
  AdvisorThreadDto,
  AdvisorThreadSummaryDto,
  ChatEventDto,
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

export async function archiveThread(threadId: string): Promise<void> {
  return apiDelete(`/advisor/threads/${threadId}`);
}

/** Consomme le flux SSE d'un tour de tchat, un evenement a la fois. */
export async function* streamChatMessage(
  threadId: string,
  text: string,
): AsyncGenerator<ChatEventDto> {
  const response = await fetch(`${API_BASE}/advisor/threads/${threadId}/messages`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, "le conseiller est injoignable");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) {
        yield JSON.parse(line.slice("data: ".length)) as ChatEventDto;
      }
    }
  }
}
