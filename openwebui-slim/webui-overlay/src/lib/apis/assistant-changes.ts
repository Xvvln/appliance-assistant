import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { RecordKind } from '$lib/apis/jiadian';

export type Schedule = { date: string; slot: string; service?: string };
export type ChangeRecord = {
	id: string;
	kind: RecordKind;
	model: string;
	name: string;
	category: string;
	status: string;
	date: string;
	slot: string;
	service: string;
	editable: boolean;
};
export type ChangeItem = ChangeRecord & {
	before: Schedule;
	proposed: Schedule;
	current?: Schedule;
	decision: 'change' | 'keep' | 'clarify';
	reason: string;
	outcome: string;
};
export type ChangeSession = {
	id: string;
	message: string;
	summary: string;
	items: ChangeItem[];
	questions: string[];
	dates: string[];
	slots: string[];
	dismissed: boolean;
	created_at: string;
	updated_at: string;
};
async function request<T>(path: string, method = 'GET', body?: object): Promise<T> {
	const response = await fetch(`${WEBUI_API_BASE_URL}/jiadian/assistant/changes/${path}`, {
		method,
		headers: { Authorization: `Bearer ${localStorage.token}`, 'Content-Type': 'application/json' },
		body: body ? JSON.stringify(body) : undefined
	});
	const result: T & { detail?: unknown } = await response.json();
	if (!response.ok)
		throw new Error(typeof result.detail === 'string' ? result.detail : '暂时无法处理，请重试');
	return result;
}
export const getChangeRecords = () =>
	request<{ records: ChangeRecord[]; dates: string[]; slots: string[] }>('records');
export const createChangePlan = (message: string) =>
	request<ChangeSession>('plan', 'POST', { message });
export const getChangeSessions = () => request<{ sessions: ChangeSession[] }>('sessions');
export const getChangeSession = (id: string) =>
	request<ChangeSession>(`sessions/${encodeURIComponent(id)}`);
export const refreshChangeSession = (id: string) =>
	request<ChangeSession>(`sessions/${encodeURIComponent(id)}/refresh`, 'POST');
export const dismissChangeSession = (id: string) =>
	request<ChangeSession>(`sessions/${encodeURIComponent(id)}/dismiss`, 'POST');
