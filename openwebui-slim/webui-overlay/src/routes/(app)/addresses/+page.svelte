<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { WEBUI_NAME, showSidebar, mobile } from '$lib/stores';
	import {
		getAddresses,
		manageAddress,
		type StoredAddress,
		type AddressAction
	} from '$lib/apis/jiadian';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ToolInteraction from '$lib/components/jiadian/ToolInteraction.svelte';

	let addresses: StoredAddress[] = [];
	let loading = true;
	let error = '';
	let busy = false;
	let mounted = false;
	let interaction: ToolInteraction;

	async function load(initial = false) {
		if (initial) loading = true;
		error = '';
		try {
			const result = await getAddresses();
			if (mounted) addresses = result.addresses;
		} catch (e) {
			if (mounted) error = e instanceof Error ? e.message : '暂时无法加载，请重试';
		} finally {
			if (mounted) loading = false;
		}
	}

	async function manage(action: AddressAction, id?: string) {
		if (busy) return;
		busy = true;
		try {
			const result = await interaction.run((sessionId, operationId, signal) =>
				manageAddress(action, id, sessionId, operationId, signal)
			);
			if (!mounted) return;
			if (result.error) toast.error(result.error);
			else if (result.status === '未提交') toast.info('未作更改，地址保持不变');
			else if (result.status === '已保存') toast.success('地址已保存');
			else if (result.status === '已删除') toast.success('地址已删除');
			else if (result.status === '已设为默认') toast.success('已设为默认地址');
			else if (result.message) toast.info(result.message);
			await load();
		} catch (e) {
			if (mounted && !(e instanceof DOMException && e.name === 'AbortError')) {
				toast.error(e instanceof Error ? e.message : '操作未完成，请重试');
			}
		} finally {
			busy = false;
		}
	}

	onMount(() => {
		mounted = true;
		void load(true);
		return () => {
			mounted = false;
		};
	});
</script>

<svelte:head><title>地址管理 / {$WEBUI_NAME}</title></svelte:head>
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
		<h1 class="text-lg font-medium">地址管理</h1>
	</header>
	<main class="flex-1 min-h-0 overflow-y-auto px-4 pb-8">
		<div class="max-w-4xl mx-auto">
			<div
				class="flex items-center justify-end gap-2 pb-3 border-b border-gray-100 dark:border-gray-850"
			>
				<button
					aria-label="刷新地址"
					title="刷新地址"
					class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
					disabled={loading || busy}
					on:click={() => load(true)}><ArrowPath className="size-4" /></button
				>
				<button
					class="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm bg-gray-900 text-white hover:bg-black dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white disabled:opacity-40"
					disabled={busy}
					on:click={() => manage('新增')}><Plus className="size-4" />新增地址</button
				>
			</div>
			{#if loading}<div class="flex justify-center py-16"><Spinner /></div>
			{:else if error}<div role="alert" class="text-sm py-8">
					{error}<button class="ml-4 underline" on:click={() => load(true)}>重试</button>
				</div>
			{:else if !addresses.length}<div class="py-16 text-center text-sm text-gray-500">
					<p>还没有保存的地址</p>
					<p class="mt-2">新增地址后，可在下单和预约报修时选择。</p>
				</div>
			{:else}
				{#each addresses as address (address.id)}
					<article
						aria-label={`${address.recipient}${address.label ? ' ' + address.label : ''}的地址`}
						class="py-5 border-b border-gray-100 dark:border-gray-850 last:border-0"
					>
						<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
							<h2 class="font-medium">{address.recipient}</h2>
							{#if address.phone}<span class="text-sm text-gray-500">{address.phone}</span>{/if}
							{#if address.label}<span class="text-xs text-gray-500">{address.label}</span>{/if}
							{#if address.is_default}<span
									class="text-xs rounded px-2 py-0.5 bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300"
									>默认</span
								>{/if}
						</div>
						<p class="mt-3 text-sm break-words">{address.region} {address.detail}</p>
						<div class="flex flex-wrap justify-end gap-2 mt-4">
							{#if !address.is_default}<button
									class="mr-auto rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
									disabled={busy}
									on:click={() => manage('设为默认', address.id)}>设为默认</button
								>{/if}
							<button
								class="rounded-lg px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
								disabled={busy}
								on:click={() => manage('删除', address.id)}>删除</button
							>
							<button
								class="rounded-lg px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 disabled:opacity-40"
								disabled={busy}
								on:click={() => manage('修改', address.id)}>修改</button
							>
						</div>
					</article>
				{/each}
			{/if}
		</div>
	</main>
</div>

<ToolInteraction bind:this={interaction} />
