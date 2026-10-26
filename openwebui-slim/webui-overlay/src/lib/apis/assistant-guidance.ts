import { WEBUI_API_BASE_URL } from '$lib/constants';

export type GuideAction = 'completed' | 'not_found' | 'different' | 'message' | 'resolved';
export type GuideStep = {
	observation: string;
	title: string;
	instruction: string;
	verification: string;
	quote: string;
	needs_service: boolean;
};
export type GuideHistory = {
	step: GuideStep;
	action: GuideAction;
	feedback: string;
	image_count: number;
};
export type GuideSession = {
	id: string;
	model: string;
	order_id: string | null;
	task: string;
	status: 'active' | 'completed';
	current_step: GuideStep;
	history: GuideHistory[];
	completed_by_user?: boolean;
};
export type GuideStart = { model: string; order_id?: string; task: string; images?: string[] };
export type GuideReply = { action: GuideAction; feedback?: string; images?: string[] };

async function request<T>(path: string, body?: GuideStart | GuideReply): Promise<T> {
	const response = await fetch(`${WEBUI_API_BASE_URL}/jiadian/assistant/guidance${path}`, {
		method: body ? 'POST' : 'GET',
		headers: {
			Authorization: `Bearer ${localStorage.token}`,
			...(body ? { 'Content-Type': 'application/json' } : {})
		},
		...(body ? { body: JSON.stringify(body) } : {})
	});
	const result: T & { detail?: unknown } = await response.json();
	if (!response.ok) {
		throw new Error(typeof result.detail === 'string' ? result.detail : '暂时无法继续，请重试。');
	}
	return result;
}

export const getGuideSessions = () => request<{ sessions: GuideSession[] }>('');
export const getGuideSession = (id: string) => request<GuideSession>(`/${encodeURIComponent(id)}`);
export const startGuidance = (body: GuideStart) => request<GuideSession>('', body);
export const continueGuidance = (id: string, body: GuideReply) =>
	request<GuideSession>(`/${encodeURIComponent(id)}/step`, body);
