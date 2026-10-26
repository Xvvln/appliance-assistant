<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { WEBUI_NAME, showSidebar, mobile } from '$lib/stores';
	import {
		getCatalog,
		getRecords,
		manageRecord,
		type Product,
		type OrderRecord,
		type ServiceTicketRecord,
		type RecordKind
	} from '$lib/apis/jiadian';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ToolInteraction from '$lib/components/jiadian/ToolInteraction.svelte';

	let orders: OrderRecord[] = [];
	let tickets: ServiceTicketRecord[] = [];
	let products: Product[] = [];
	let tab: RecordKind = 'orders';
	let loading = true;
	let error = '';
	let busy = '';
	let interaction: ToolInteraction;
	let mounted = false;
	$: productByModel = new Map(products.map((product) => [product.model, product]));

	const orderNumber = (id: string) => id.replace(/^DEMO-/, '');
	const money = (value: number) =>
		value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

	async function load(initial = false) {
		if (initial) loading = true;
		error = '';
		try {
			const records = await getRecords();
			if (!mounted) return;
			orders = records.orders;
			tickets = records.tickets;
		} catch (e) {
			if (mounted) error = e instanceof Error ? e.message : '暂时无法加载，请重试';
		} finally {
			if (mounted) loading = false;
		}
	}

	async function manage(kind: RecordKind, id: string, action: '修改' | '取消') {
		if (busy) return;
		busy = id;
		try {
			const result = await interaction.run((sessionId, operationId, signal) =>
				manageRecord(kind, id, action, sessionId, operationId, signal)
			);
			if (!mounted) return;
			if (result.error) toast.error(result.error);
			else if (result.status === '未提交') toast.info('未作更改，原记录保持不变');
			else if (result.status === '已修改' || result.status === '已取消') {
				toast.success(`${kind === 'orders' ? '订单' : '报修预约'}${result.status}`);
			} else if (result.message) toast.info(result.message);
			await load();
		} catch (e) {
			if (mounted && !(e instanceof DOMException && e.name === 'AbortError')) {
				toast.error(e instanceof Error ? e.message : '操作未完成，请重试');
			}
		} finally {
			busy = '';
		}
	}

	onMount(() => {
		mounted = true;
		void load(true);
		void getCatalog()
			.then((result) => {
				if (mounted) products = result.products;
			})
			.catch(() => {});
		return () => {
			mounted = false;
		};
	});
</script>

<svelte:head><title>订单与售后 / {$WEBUI_NAME}</title></svelte:head>
<div
	class="flex flex-col flex-1 min-w-0 h-screen max-h-[100dvh] {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: 'md:max-w-[calc(100%-42px)]'}"
>
	<header class="flex shrink-0 items-center gap-2 px-4 py-3">
		{#if $mobile}<button
				aria-label="展开侧边栏"
				class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850"
				on:click={() => showSidebar.set(!$showSidebar)}><Sidebar /></button
			>{/if}
		<h1 class="text-lg font-medium">订单与售后</h1>
	</header>
	<main class="flex-1 min-h-0 overflow-y-auto px-4 pb-8">
		<div class="max-w-4xl mx-auto">
			<div
				class="flex items-center justify-between gap-3 border-b border-gray-100 dark:border-gray-850 mb-2"
			>
				<div class="flex items-center gap-5" aria-label="记录类型">
					<button
						class="py-3 text-sm border-b-2 {tab === 'orders'
							? 'border-gray-900 dark:border-gray-100 font-medium'
							: 'border-transparent text-gray-500'}"
						aria-pressed={tab === 'orders'}
						on:click={() => (tab = 'orders')}
						>订单 <span class="ml-1 text-gray-500">{orders.length}</span></button
					>
					<button
						class="py-3 text-sm border-b-2 {tab === 'tickets'
							? 'border-gray-900 dark:border-gray-100 font-medium'
							: 'border-transparent text-gray-500'}"
						aria-pressed={tab === 'tickets'}
						on:click={() => (tab = 'tickets')}
						>售后预约 <span class="ml-1 text-gray-500">{tickets.length}</span></button
					>
				</div>
				<button
					aria-label="刷新记录"
					title="刷新记录"
					class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
					disabled={loading || !!busy}
					on:click={() => load(true)}><ArrowPath className="size-4" /></button
				>
			</div>
			{#if loading}<div class="flex justify-center py-16"><Spinner /></div>
			{:else if error}<div role="alert" class="text-sm py-8">
					{error}<button class="ml-4 underline" on:click={() => load(true)}>重试</button>
				</div>
			{:else if tab === 'orders'}
				{#if !orders.length}<div class="py-16 text-center text-sm text-gray-500">
						<p>还没有订单</p>
						<a
							href="/shop"
							class="inline-block mt-3 text-gray-800 dark:text-gray-200 hover:underline"
							>去商城看看</a
						>
					</div>{/if}
				{#each orders as order (order.order_id)}
					{@const product = productByModel.get(order.model)}
					<article
						aria-label={`订单 ${orderNumber(order.order_id)}`}
						class="py-5 border-b border-gray-100 dark:border-gray-850 last:border-0"
					>
						<div class="flex gap-4">
							{#if product}<img
									src={`/static/jiadian/products/${order.model}.png`}
									alt={product.name}
									class="size-16 sm:size-20 shrink-0 rounded-lg bg-white object-contain p-1"
									loading="lazy"
								/>{/if}
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap justify-between items-baseline gap-x-4 gap-y-1">
									<h2 class="font-medium">{product?.name ?? order.model}</h2>
									<span class="text-xs text-gray-500">{order.status}</span>
								</div>
								<p class="mt-1 text-xs text-gray-500">{order.model} · {order.quantity} 台</p>
								<p class="mt-2 text-sm font-medium">¥{money(order.total_yuan)}</p>
							</div>
						</div>
						<dl class="mt-4 grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
							<dt class="text-gray-500">配送</dt>
							<dd>{order.delivery_date} {order.delivery_slot} · {order.service}</dd>
							<dt class="text-gray-500">收货人</dt>
							<dd>
								{order.recipient}{#if order.shipping_address?.phone}<span class="ml-3 text-gray-500"
										>{order.shipping_address.phone}</span
									>{/if}
							</dd>
							<dt class="text-gray-500">地址</dt>
							<dd class="break-words">{order.delivery_address}</dd>
							<dt class="text-gray-500">订单号</dt>
							<dd class="text-gray-500 break-all">{orderNumber(order.order_id)}</dd>
						</dl>
						<div class="flex flex-wrap justify-end items-center gap-2 mt-4">
							{#if product}<a
									class="mr-auto text-xs text-gray-500 hover:underline py-2"
									href={`/workspace/knowledge/washer-cloud?doc=${encodeURIComponent(order.model + '_说明书')}`}
									>使用说明书</a
								>{/if}
							{#if order.status === '已确认，待配送'}
								<button
									class="rounded-lg px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
									disabled={!!busy}
									on:click={() => manage('orders', order.order_id, '取消')}>取消订单</button
								>
								<button
									class="rounded-lg px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 disabled:opacity-40"
									disabled={!!busy}
									on:click={() => manage('orders', order.order_id, '修改')}>修改订单</button
								>
							{/if}
						</div>
					</article>
				{/each}
			{:else}
				{#if !tickets.length}<p class="py-16 text-center text-sm text-gray-500">
						还没有报修预约
					</p>{/if}
				{#each tickets as ticket (ticket.ticket_id)}
					{@const product = productByModel.get(ticket.model)}
					<article
						aria-label={`报修预约 ${ticket.ticket_id}`}
						class="py-5 border-b border-gray-100 dark:border-gray-850 last:border-0"
					>
						<div class="flex gap-4">
							{#if product}<img
									src={`/static/jiadian/products/${ticket.model}.png`}
									alt={product.name}
									class="size-16 sm:size-20 shrink-0 rounded-lg bg-white object-contain p-1"
									loading="lazy"
								/>{/if}
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap justify-between items-baseline gap-x-4 gap-y-1">
									<h2 class="font-medium">{product?.name ?? ticket.model}</h2>
									<span class="text-xs text-gray-500">{ticket.status}</span>
								</div>
								<p class="mt-1 text-xs text-gray-500">{ticket.model}</p>
								<p class="mt-2 text-sm break-words whitespace-pre-line">{ticket.issue}</p>
							</div>
						</div>
						<dl class="mt-4 grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
							<dt class="text-gray-500">预约</dt>
							<dd>{ticket.appointment.date} {ticket.appointment.slot}</dd>
							<dt class="text-gray-500">联系人</dt>
							<dd>
								{ticket.address.recipient}{#if ticket.address.phone}<span class="ml-3 text-gray-500"
										>{ticket.address.phone}</span
									>{/if}
							</dd>
							<dt class="text-gray-500">地址</dt>
							<dd class="break-words">{ticket.address.region} {ticket.address.detail}</dd>
							<dt class="text-gray-500">预约号</dt>
							<dd class="text-gray-500 break-all">{ticket.ticket_id}</dd>
							{#if ticket.order_id}<dt class="text-gray-500">订单号</dt>
								<dd class="text-gray-500 break-all">{orderNumber(ticket.order_id)}</dd>{/if}
						</dl>
						{#if ticket.status === '待受理'}<div class="flex flex-wrap justify-end gap-2 mt-4">
								<button
									class="rounded-lg px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
									disabled={!!busy}
									on:click={() => manage('tickets', ticket.ticket_id, '取消')}>取消预约</button
								><button
									class="rounded-lg px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 disabled:opacity-40"
									disabled={!!busy}
									on:click={() => manage('tickets', ticket.ticket_id, '修改')}>修改预约</button
								>
							</div>{/if}
					</article>
				{/each}
			{/if}
		</div>
	</main>
</div>

<ToolInteraction bind:this={interaction} />
