import { apiGet, apiPost } from "./client";

/** Reflète `InvitationOut` (backend/app/api/v1/endpoints/workspaces.py). */
export interface InvitationDto {
  id: string;
  workspace_id: string;
  invited_email: string;
  token: string;
  status: string;
}

/** `GET /invitations/{token}` est public (aucune dépendance d'auth côté backend) :
 * un visiteur non connecté doit pouvoir consulter l'invitation avant de s'inscrire. */
export async function getInvitation(token: string): Promise<InvitationDto> {
  return apiGet<InvitationDto>(`/invitations/${token}`);
}

/** `POST /invitations/{token}/accept` requiert une session (cookie) — voir `onAccept`
 * dans la page d'invitation, qui redirige vers `/register` si l'utilisateur n'est pas connecté. */
export async function acceptInvitation(token: string): Promise<void> {
  await apiPost(`/invitations/${token}/accept`);
}
