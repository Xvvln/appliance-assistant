import { WEBUI_API_BASE_URL } from '$lib/constants';

export type PreviewFile = { id: string; url: string; name: string };
export type PreviewSession = {
	id: string; model: string; name: string; instruction: string;
	status: 'queued' | 'generating' | 'completed' | 'failed';
	original: PreviewFile; image?: PreviewFile; error?: string; available_at: number;
	dimensions?: { width: number; height: number; depth: number };
	fit: { status: string; message: string; checks?: { label: string; measured_mm: number; required_mm: number; difference_mm: number }[] };
};
export type PreviewInput = {
	model: string; image: string; instruction: string; request_id: string;
	dimensions?: { width: number; height: number; depth: number };
};

async function request<T>(path: string, body?: PreviewInput): Promise<T> {
	const response = await fetch(`${WEBUI_API_BASE_URL}/jiadian/assistant/preview${path}`, {
		method: body ? 'POST' : 'GET',
		headers: { Authorization: `Bearer ${localStorage.token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
		...(body ? { body: JSON.stringify(body) } : {})
	});
	const result = await response.json();
	if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '图片暂时无法加载，请重试');
	return result as T;
}
export const listPreviews = () => request<{ sessions: PreviewSession[]; requests_per_minute: number }>('');
export const getPreview = (id: string) => request<PreviewSession>(`/${encodeURIComponent(id)}`);
export const createPreview = (body: PreviewInput) => request<PreviewSession>('', body);
export async function previewFile(url: string): Promise<Blob> {
	const response = await fetch(url, { headers: { Authorization: `Bearer ${localStorage.token}` } });
	if (!response.ok) throw new Error('图片未能加载，请刷新后重试');
	return response.blob();
}
