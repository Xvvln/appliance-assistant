<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, showSidebar, mobile } from '$lib/stores';
	import { getCatalog, type Product } from '$lib/apis/jiadian';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	let products: Product[] = [];
	let query = '';
	let type = '';
	let category = '';
	let drying = false;
	let selected: string[] = [];
	let loading = true;
	let error = '';
	let compare = false;
	$: visible = products.filter(
		(p) =>
			`${p.name} ${p.model} ${p.category} ${p.type}`.toLowerCase().includes(query.toLowerCase()) &&
			(!category || p.category === category) &&
			(!type || p.type === type) &&
			(!drying || (p.dry_kg ?? 0) > 0)
	);
	$: chosen = products.filter((p) => selected.includes(p.model));
	$: categories = [...new Set(products.map((p) => p.category))];
	$: types = [...new Set(products.filter((p) => !category || p.category === category).map((p) => p.type))];
	$: specLabels = [...new Set(chosen.flatMap((p) => Object.keys(p.comparison_specs)))];
	$: rows = [
		['价格', (p: Product) => `¥${p.price_yuan.toLocaleString('zh-CN')}`],
		['库存', (p: Product) => `${p.stock} 台`],
		...specLabels.map((label): [string, (p: Product) => string] => [label, (p) => p.comparison_specs[label] ?? '—'])
	] as [string, (p: Product) => string][];
	function changeCategory() {
		type = '';
		drying = false;
	}
	async function load() {
		loading = true;
		error = '';
		try {
			products = (await getCatalog()).products;
		} catch (e) {
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			loading = false;
		}
	}
	function choose(p: Product) {
		goto(
			'/?' +
				new URLSearchParams({
					models: 'jiadian-assistant',
					q: `我选择 ${p.name}（${p.model}），请继续订购，先核对配送和安装选项。`
				})
		);
	}
	onMount(load);
</script>

<svelte:head><title>商城 / {$WEBUI_NAME}</title></svelte:head>
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
		<h1 class="text-lg font-medium">商城</h1>
	</header>
	<main class="flex-1 min-h-0 overflow-y-auto px-4 pb-8">
		<div class="max-w-6xl mx-auto">
			<div class="flex flex-wrap gap-3 items-center mb-6">
				<div
					class="flex items-center gap-2 bg-gray-50 dark:bg-gray-850 rounded-xl px-3 min-w-40 flex-1"
				>
					<Search className="size-4 text-gray-500" /><input
						aria-label="搜索产品"
						placeholder="搜索产品或型号"
						bind:value={query}
						class="w-full bg-transparent py-3 text-sm outline-none"
					/>
				</div>
				<select aria-label="产品品类" bind:value={category} on:change={changeCategory}
					class="bg-gray-50 dark:bg-gray-850 rounded-xl px-3 py-3 text-sm">
					<option value="">全部品类</option>
					{#each categories as item}<option value={item}>{item}</option>{/each}
				</select>
				<select
					aria-label="产品类型"
					bind:value={type}
					class="bg-gray-50 dark:bg-gray-850 rounded-xl px-3 py-3 text-sm"
					><option value="">全部类型</option>{#each types as item}<option value={item}
							>{item}</option
						>{/each}</select
				>
				{#if !category || category === '洗衣机'}<label class="flex items-center gap-2 text-sm py-3"
					><input
						type="checkbox"
						bind:checked={drying}
						class="accent-gray-900 dark:accent-gray-100"
					/>需要烘干</label
				>{/if}
			</div>
			{#if loading}<div class="flex justify-center py-16"><Spinner /></div>
			{:else if error}<div role="alert" class="text-sm py-8">
					{error}<button class="ml-4 underline" on:click={load}>重试</button>
				</div>
			{:else if !visible.length}<p class="text-sm text-gray-500 py-12 text-center">
					没有符合条件的产品，请调整筛选条件。
				</p>
			{:else}<div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-10">
					{#each visible as p (p.model)}<article class="min-w-0 flex flex-col">
							<div class="rounded-xl bg-white overflow-hidden">
								<img
									src={`/static/jiadian/products/${p.model}.png`}
									alt={`${p.name} ${p.model} ${p.category} ${p.type}`}
									class="w-full aspect-[4/3] object-contain p-4"
									loading="lazy"
								/>
							</div>
							<h2 class="font-medium mt-3">{p.name}</h2>
							<p class="text-xs text-gray-500 mt-1">{p.model} · {p.type}</p>
							<p class="text-sm text-gray-600 dark:text-gray-400 mt-2">{p.features.join(' · ')}</p>
							<div class="flex gap-3 items-baseline my-3">
								<span class="text-lg font-semibold">¥{p.price_yuan.toLocaleString('zh-CN')}</span
								><span class="text-xs text-gray-500">库存 {p.stock}</span>
							</div>
							<div class="flex justify-between gap-3 items-center mt-auto">
								<label class="flex items-center gap-2 text-sm min-h-11"
									><input
										aria-label={`对比 ${p.model}`}
										type="checkbox"
										bind:group={selected}
										value={p.model}
										disabled={selected.length >= 3 && !selected.includes(p.model)}
										class="accent-gray-900 dark:accent-gray-100"
									/>加入对比</label
								>
								<button
									disabled={p.stock <= 0}
									aria-label={`选购 ${p.model}`}
									class="rounded-xl px-4 py-2.5 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 disabled:opacity-40"
									on:click={() => choose(p)}>{p.stock > 0 ? '继续选购' : '暂时缺货'}</button
								>
							</div>
							<div class="flex gap-4 mt-2 text-xs text-gray-500">
								<a
									class="hover:underline"
									href={`/workspace/knowledge/washer-cloud?doc=${encodeURIComponent(p.model + '_参数')}`}
									>产品资料</a
								><a
									class="hover:underline"
									href={`/workspace/knowledge/washer-cloud?doc=${encodeURIComponent(p.model + '_说明书')}`}
									>使用说明</a
								>
							</div>
						</article>{/each}
				</div>{/if}
		</div>
	</main>
	{#if selected.length}
		<footer
			aria-label="产品对比操作"
			class="shrink-0 border-t border-gray-100 dark:border-gray-850 px-4 py-3"
		>
			<div class="max-w-6xl mx-auto flex items-center justify-between gap-4">
				<span class="text-sm text-gray-500">已选 {selected.length} 款，最多对比 3 款</span>
				<button
					class="shrink-0 whitespace-nowrap rounded-xl px-4 py-2.5 bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 disabled:opacity-40 text-sm"
					disabled={selected.length < 2}
					on:click={() => (compare = true)}>对比所选</button
				>
			</div>
		</footer>
	{/if}
</div>
<Modal bind:show={compare} size="xl" ariaLabel="产品对比">
	<div class="p-3">
		<div class="flex justify-between items-center mb-4">
			<h2 class="text-lg font-medium">产品对比</h2>
			<button
				class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850"
				aria-label="关闭对比"
				on:click={() => (compare = false)}><XMark /></button
			>
		</div>
		<div class="overflow-x-auto">
			<table class="w-full text-sm text-left">
				<thead
					><tr
						><th class="p-3 font-medium">对比项目</th>{#each chosen as p}<th
								class="p-3 min-w-40 font-medium"
								>{p.name}<span class="block text-xs text-gray-500 mt-1">{p.model}</span></th
							>{/each}</tr
					></thead
				><tbody
					>{#each rows as [label, value]}<tr class="border-t border-gray-100 dark:border-gray-850"
							><th class="p-3 font-normal text-gray-500 whitespace-nowrap">{label}</th
							>{#each chosen as p}<td class="p-3">{value(p)}</td>{/each}</tr
						>{/each}</tbody
				>
			</table>
		</div>
	</div>
</Modal>
