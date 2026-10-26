import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { Product } from '$lib/apis/jiadian';

export type PlanCategory = '洗衣机' | '空调' | '冰箱';
export type PlanRequirements = {
	min_capacity_kg?: number | null;
	requires_drying?: boolean | null;
	max_installation_depth_mm?: number | null;
	min_volume_l?: number | null;
	horsepower?: number | null;
	min_cooling_w?: number | null;
	room_area_m2?: number | null;
};
export type PlanConstraints = {
	budget_yuan: number | null;
	categories: PlanCategory[];
	requirements: Partial<Record<PlanCategory, PlanRequirements>>;
	locked_models: Partial<Record<PlanCategory, string | null>>;
	priority: PlanCategory | null;
};
export type AppliancePlan = {
	id: string;
	products: Product[];
	total_yuan: number;
	remaining_yuan: number;
	reason: string;
};
export type PlanSession = {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
	constraints: PlanConstraints;
	summary: string[];
	plans: AppliancePlan[];
	differences: string[];
	clarification: string;
	problems: string[];
	no_solution: { minimum_total_yuan: number; shortfall_yuan: number } | null;
	notes: string[];
	message: string;
};
export type PlanUpdate = {
	message?: string;
	session_id?: string;
	constraints?: Partial<PlanConstraints>;
};

async function request<T>(path: string, body?: PlanUpdate): Promise<T> {
	const response = await fetch(`${WEBUI_API_BASE_URL}/jiadian/assistant/plans${path}`, {
		method: body ? 'POST' : 'GET',
		headers: {
			Authorization: `Bearer ${localStorage.token}`,
			...(body ? { 'Content-Type': 'application/json' } : {})
		},
		...(body ? { body: JSON.stringify(body) } : {})
	});
	if (!response.ok) {
		const error: { detail?: unknown } = await response.json().catch(() => ({}));
		throw new Error(typeof error.detail === 'string' ? error.detail : '方案暂时无法更新，请重试。');
	}
	return response.json() as Promise<T>;
}

export const getPlanSessions = () => request<{ sessions: PlanSession[] }>('');
export const getPlanSession = (id: string) => request<PlanSession>(`/${encodeURIComponent(id)}`);
export const updatePlan = (body: PlanUpdate) => request<PlanSession>('', body);
