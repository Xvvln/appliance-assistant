<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import {
		getPlanSessions, getPlanSession, updatePlan,
		type PlanCategory, type PlanConstraints, type PlanSession
	} from '$lib/apis/assistant-plans';
	import type { Product } from '$lib/apis/jiadian';

	const categories: PlanCategory[] = ['洗衣机', '空调', '冰箱'];
	let sessions: PlanSession[] = [];
	let state: PlanSession | null = null;
	let selectedSession = '';
	let selectedCategories: PlanCategory[] = [...categories];
	let budget: number | undefined;
	let message = '';
	let error = '';
	let loading = true;
	let busy = false;
	const money = (amount: number) => amount.toLocaleString('zh-CN', { maximumFractionDigits: 2 });

	function show(result: PlanSession | null) {
		state = result;
		selectedSession = result?.id ?? '';
		budget = result?.constraints.budget_yuan ?? undefined;
		selectedCategories = [...(result?.constraints.categories ?? categories)];
		error = '';
		message = '';
	}
	async function load() {
		loading = true;
		try {
			sessions = (await getPlanSessions()).sessions;
			show(sessions[0] ?? null);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : '暂时无法加载方案。';
		} finally {
			loading = false;
		}
	}
	async function restore() {
		if (!selectedSession) return show(null);
		loading = true;
		try { show(await getPlanSession(selectedSession)); }
		catch (cause) { error = cause instanceof Error ? cause.message : '暂时无法加载方案。'; }
		finally { loading = false; }
	}
	async function submit(extra: Partial<PlanConstraints> = {}) {
		if (busy) return;
		if (!selectedCategories.length) { error = '请至少选择一个品类。'; return; }
		const patch: Partial<PlanConstraints> = { ...extra };
		if ((budget ?? null) !== (state?.constraints.budget_yuan ?? null)) patch.budget_yuan = budget ?? null;
		const oldCategories = state?.constraints.categories ?? categories;
		if (selectedCategories.join('|') !== oldCategories.join('|')) patch.categories = selectedCategories;
		busy = true;
		error = '';
		try {
			const result = await updatePlan({ message: message.trim(), session_id: state?.id, constraints: patch });
			sessions = [result, ...sessions.filter((item) => item.id !== result.id)];
			show(result);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : '暂时无法更新方案。';
		} finally { busy = false; }
	}
	function toggleLock(item: Product) {
		const category = item.category as PlanCategory;
		const isLocked = state?.constraints.locked_models[category] === item.model;
		void submit({ locked_models: { [category]: isLocked ? null : item.model } });
	}
	function buy(item: Product) {
		goto('/?' + new URLSearchParams({
			models: 'jiadian-assistant',
			q: `我选择 ${item.name}（${item.model}），请继续订购，先核对配送和安装选项。`
		}));
	}
	onMount(load);
</script>

<div class="space-y-6">
	{#if sessions.length}
		<div class="flex flex-wrap gap-2 items-center">
			<select aria-label="已保存的方案" bind:value={selectedSession} on:change={restore}
				disabled={busy || loading} class="min-w-0 max-w-full flex-1 rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2.5 text-sm">
				<option value="">新方案</option>
				{#each sessions as item (item.id)}<option value={item.id}>{item.title}</option>{/each}
			</select>
			<button disabled={busy || loading} on:click={() => show(null)}
				class="rounded-xl px-3 py-2.5 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40">新方案</button>
		</div>
	{/if}
	{#if loading}<div class="flex justify-center py-10"><Spinner /></div>{:else}
		<form on:submit|preventDefault={() => submit()} class="space-y-3">
			<p class="text-sm text-gray-500">把预算和使用需求一起考虑，每个品类先搭配一台。条件改变后，可以继续调整。</p>
			<div class="flex flex-wrap gap-x-5 gap-y-3 items-center">
				<label class="flex gap-2 items-center text-sm">总预算
					<input aria-label="总预算" type="number" min="1" step="1" bind:value={budget} disabled={busy}
						placeholder="元" class="w-28 rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2.5 outline-none" />
				</label>
				{#each categories as category}
					<label class="flex gap-2 items-center text-sm"><input type="checkbox" bind:group={selectedCategories}
						value={category} disabled={busy} class="accent-gray-900 dark:accent-gray-100" />{category}</label>
				{/each}
			</div>
			<textarea aria-label="家电方案需求" bind:value={message} disabled={busy} rows="3" maxlength="4000"
				placeholder={state ? '例如：预算增加到 9000 元，其他条件保留；冰箱要 400 升以上。' : '例如：总预算 8000 元，洗衣机要能烘干，冰箱 300 升以上，空调要 1.5 匹。'}
				class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-4 py-3 text-sm outline-none resize-y"></textarea>
			<div class="flex justify-end items-center gap-3">
				{#if busy}<span class="text-sm text-gray-500" aria-live="polite">正在核对商品并整理搭配…</span><Spinner />{/if}
				<button type="submit" disabled={busy} class="rounded-xl px-4 py-2.5 text-sm bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 disabled:opacity-40">
					{state ? '调整方案' : '生成方案'}</button>
			</div>
		</form>
	{/if}
	{#if error}<p role="alert" class="text-sm text-red-600 dark:text-red-400">{error}
		{#if !state && loading === false && !sessions.length}<button class="underline ml-2" on:click={load}>重新加载</button>{/if}</p>{/if}
	{#if state}
		<div class="flex flex-wrap gap-2" aria-label="已确认的方案条件">
			{#each state.summary as item}<span class="px-3 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 text-xs">{item}</span>{/each}
		</div>
		{#if state.differences.length}<div class="text-sm space-y-1">
			<p class="font-medium">本次调整</p>
			{#each state.differences as item}<p class="text-gray-500">{item}</p>{/each}
		</div>{/if}
		{#if state.clarification}<p class="text-sm text-gray-600 dark:text-gray-400">{state.clarification}</p>{/if}
		{#each state.problems as problem}<p role="status" class="text-sm">{problem}</p>{/each}
		{#if state.plans.length}
			<div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
				{#each state.plans as plan, index (plan.id)}
					<article class="min-w-0 border border-gray-100 dark:border-gray-850 rounded-xl p-4 flex flex-col">
						<div class="flex gap-3 items-baseline justify-between"><h2 class="text-base font-medium">方案 {index + 1}</h2>
							<span class="font-semibold whitespace-nowrap">¥{money(plan.total_yuan)}</span></div>
						<p class="text-xs text-gray-500 mt-1">预算剩余 ¥{money(plan.remaining_yuan)}</p>
						<p class="text-sm mt-3 text-gray-600 dark:text-gray-400">{plan.reason}</p>
						<div class="divide-y divide-gray-100 dark:divide-gray-850 mt-2">
							{#each plan.products as item (item.model)}
								<div class="py-4 space-y-3">
									<div class="flex gap-3 min-w-0">
										<img src={`/static/jiadian/products/${item.model}.png`} alt={`${item.name} ${item.model}`}
											class="w-16 h-16 shrink-0 object-contain rounded-lg bg-white" loading="lazy" />
										<div class="min-w-0"><h3 class="text-sm font-medium">{item.name}</h3><p class="text-xs text-gray-500 mt-1">{item.model} · {item.category}</p>
											<p class="text-sm mt-1">¥{money(item.price_yuan)} <span class="text-xs text-gray-500 ml-1">库存 {item.stock}</span></p></div>
									</div>
									<p class="text-xs text-gray-500">{item.features.join(' · ')}</p>
									<details class="text-xs text-gray-500"><summary class="cursor-pointer">查看取舍与资料</summary>
										<p class="mt-2">{item.tradeoff}</p><a class="inline-block mt-2 underline" href={item.manual_url} target="_blank" rel="noreferrer">使用说明书</a></details>
									<div class="flex justify-between gap-2 items-center">
										<button disabled={busy} on:click={() => toggleLock(item)} aria-pressed={state.constraints.locked_models[item.category as PlanCategory] === item.model}
											class="text-xs px-2 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40">
											{state.constraints.locked_models[item.category as PlanCategory] === item.model ? '解除保留' : '保留这款'}</button>
										<button disabled={busy} on:click={() => buy(item)} class="text-xs px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 disabled:opacity-40">继续选购</button>
									</div>
								</div>
							{/each}
						</div>
					</article>
				{/each}
			</div>
			<p class="text-xs text-gray-500">价格和库存以本次查询为准，订购时会再次核对。点击“保留这款”，后续搭配会继续使用该型号。</p>
		{/if}
		{#each state.notes as note}<p class="text-xs text-gray-500">{note}</p>{/each}
	{/if}
</div>
