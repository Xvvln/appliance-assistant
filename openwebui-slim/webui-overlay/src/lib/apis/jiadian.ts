import { WEBUI_API_BASE_URL } from '$lib/constants';

export type Product = {
	model: string;
	name: string;
	type: string;
	category: string;
	comparison_specs: Record<string, string>;
	wash_kg?: number;
	dry_kg?: number;
	width_mm: number;
	height_mm: number;
	depth_mm: number;
	installation_mm?: number[];
	price_yuan: number;
	stock: number;
	features: string[];
	tradeoff: string;
	auto_dose?: boolean;
	wifi: boolean;
	drying?: string;
	spec_url: string;
	manual_url: string;
};
export type ProductDocument = { id: string; model: string; kind: string; name: string };
export type CloudKnowledge = {
	id: string;
	name: string;
	description: string;
	file_count: number;
	updated_at: number;
	documents: ProductDocument[];
};
export type RecordAddress = {
	id: string;
	recipient: string;
	phone: string;
	region: string;
	detail: string;
	label: string;
};
export type StoredAddress = RecordAddress & { is_default: number };
export type AddressAction = '新增' | '修改' | '删除' | '设为默认';
export type ManageAddressResult = {
	status?: '已保存' | '已删除' | '已设为默认' | '未提交';
	error?: string;
	message?: string;
	address_id?: string;
};
export type OrderRecord = {
	order_id: string;
	model: string;
	quantity: number;
	unit_price_yuan: number;
	total_yuan: number;
	status: string;
	created_at: string;
	delivery_date: string;
	delivery_slot: string;
	service: string;
	recipient: string;
	delivery_address: string;
	shipping_address?: RecordAddress;
};
export type ServiceTicketRecord = {
	ticket_id: string;
	order_id: string | null;
	model: string;
	issue: string;
	status: string;
	created_at: string;
	appointment: { date: string; slot: string };
	address: RecordAddress;
};
export type RecordKind = 'orders' | 'tickets';
export type ManageRecordResult = {
	error?: string;
	status?: string;
	message?: string;
	order?: OrderRecord;
	ticket?: ServiceTicketRecord;
};
async function get<T>(path: string): Promise<T> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/jiadian/${path}`, {
		headers: { Authorization: `Bearer ${localStorage.token}` }
	});
	if (!res.ok) throw new Error('暂时无法加载，请重试');
	return res.json();
}
export const getCatalog = () => get<{ products: Product[] }>('catalog');
export const getCloudKnowledge = () => get<CloudKnowledge>('knowledge');
export const getProductDocument = (id: string) =>
	get<{ content: string }>(`knowledge/${encodeURIComponent(id)}`);
export const getRecords = () =>
	get<{ orders: OrderRecord[]; tickets: ServiceTicketRecord[] }>('records');
export async function manageRecord(
	kind: RecordKind,
	id: string,
	action: '修改' | '取消',
	sessionId: string,
	operationId: string,
	signal?: AbortSignal,
	scheduleDraft?: { date?: string; slot?: string }
): Promise<ManageRecordResult> {
	return post<ManageRecordResult>(
		`records/${kind}/${encodeURIComponent(id)}/manage`,
		{ action, session_id: sessionId, operation_id: operationId, schedule_draft: scheduleDraft },
		signal
	);
}
export const getAddresses = () => get<{ addresses: StoredAddress[] }>('addresses');
export const manageAddress = (
	action: AddressAction,
	id: string | undefined,
	sessionId: string,
	operationId: string,
	signal?: AbortSignal
) =>
	post<ManageAddressResult>(
		'addresses/manage',
		{
			action,
			address_id: id,
			session_id: sessionId,
			operation_id: operationId
		},
		signal
	);

async function post<T>(
	path: string,
	body: Record<string, unknown>,
	signal?: AbortSignal
): Promise<T> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/jiadian/${path}`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${localStorage.token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(body),
		signal
	});
	const result: T & { detail?: unknown } = await res.json();
	if (!res.ok) {
		throw new Error(typeof result.detail === 'string' ? result.detail : '操作未完成，请重试');
	}
	return result;
}
