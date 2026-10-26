<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { manageRecord } from '$lib/apis/jiadian';
	import {
		createChangePlan,
		getChangeSessions,
		getChangeSession,
		refreshChangeSession,
		dismissChangeSession,
		type ChangeSession,
		type ChangeItem
	} from '$lib/apis/assistant-changes';
	import ToolInteraction from '$lib/components/jiadian/ToolInteraction.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	let message = '';
	let session: ChangeSession | null = null;
	let history: ChangeSession[] = [];
	let selected: string[] = [];
	let showRetained = false;
	let historyId = '';
	let busy = false;
	let generating = false;
	let error = '';
	let mounted = false;
	let interaction: ToolInteraction;
	const key = (item: ChangeItem) => `${item.kind}:${item.id}`;
	const selectable = (item: ChangeItem) =>
		item.editable && item.decision === 'change' && item.outcome === '未变更' && !session?.dismissed;
	const recordNumber = (id: string) => id.replace(/^DEMO-/, '');
	$: chosen =
		session?.items.filter((item) => selected.includes(key(item)) && selectable(item)) ?? [];
	$: affectedItems = session?.items.filter((item) => item.decision !== 'keep') ?? [];
	$: retainedItems = session?.items.filter((item) => item.decision === 'keep') ?? [];
	$: visibleItems = showRetained ? [...affectedItems, ...retainedItems] : affectedItems;

	async function loadHistory() {
		try {
			const result = await getChangeSessions();
			if (mounted) history = result.sessions;
		} catch (e) {
			if (mounted) error = e instanceof Error ? e.message : '暂时无法加载记录';
		}
	}
	async function openHistory() {
		if (!historyId) return;
		busy = true;
		error = '';
		try {
			const saved = await getChangeSession(historyId);
			if (!mounted) return;
			session = saved;
			message = saved.message;
			selected = [];
			showRetained = false;
		} catch (e) {
			error = e instanceof Error ? e.message : '暂时无法加载记录';
		} finally {
			busy = false;
		}
	}
	async function plan() {
		if (!message.trim() || busy) return;
		busy = true;
		generating = true;
		error = '';
		try {
			const result = await createChangePlan(message.trim());
			if (!mounted) return;
			session = result;
			selected = [];
			showRetained = false;
			historyId = result.id;
			await loadHistory();
		} catch (e) {
			if (mounted) error = e instanceof Error ? e.message : '暂时无法生成建议';
		} finally {
			busy = false;
			generating = false;
		}
	}
	async function applySelected() {
		if (!session || busy || !chosen.length) return;
		busy = true;
		error = '';
		const sessionId = session.id;
		try {
			for (const item of chosen) {
				const result = await interaction.run((sessionId, operationId, signal) =>
					manageRecord(item.kind, item.id, '修改', sessionId, operationId, signal, {
						date: item.proposed.date,
						slot: item.proposed.slot
					})
				);
				if (!mounted) return;
				session = await refreshChangeSession(sessionId);
				selected = selected.filter((id) => id !== key(item));
				if (result.error) {
					toast.error(result.error);
					break;
				}
				if (result.status === '未提交') {
					toast.info('未提交修改，原安排保持不变');
					break;
				}
				if (result.status === '已修改') toast.success(`${item.name}的安排已更新`);
			}
			await loadHistory();
		} catch (e) {
			if (mounted && !(e instanceof DOMException && e.name === 'AbortError'))
				error = e instanceof Error ? e.message : '操作未完成，请刷新查看最新记录';
		} finally {
			busy = false;
		}
	}
	async function dismiss() {
		if (!session || busy) return;
		busy = true;
		try {
			session = await dismissChangeSession(session.id);
			selected = [];
			await loadHistory();
		} catch (e) {
			error = e instanceof Error ? e.message : '暂时无法取消建议';
		} finally {
			busy = false;
		}
	}
	onMount(() => {
		mounted = true;
		void loadHistory();
		return () => {
			mounted = false;
		};
	});
</script>

<div class="space-y-5">
	<form on:submit|preventDefault={plan} class="space-y-3">
		<label for="change-message" class="block text-sm font-medium">哪些安排需要调整？</label>
		<textarea
			id="change-message"
			bind:value={message}
			rows="3"
			maxlength="4000"
			disabled={busy}
			placeholder="这周出差，洗衣机配送往后挪一天，空调的安装安排保持不变。"
			class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-4 py-3 text-sm resize-y outline-none focus:ring-1 focus:ring-gray-400 disabled:opacity-50"
		></textarea>
		<div class="flex flex-wrap justify-between gap-3 items-center">
			{#if history.length}<select
					aria-label="查看以往调整建议"
					bind:value={historyId}
					on:change={openHistory}
					disabled={busy}
					class="max-w-full sm:max-w-[65%] bg-gray-50 dark:bg-gray-850 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
					><option value="">以往建议</option>{#each history as entry}<option value={entry.id}
							>{entry.message.slice(0, 36)}</option
						>{/each}</select
				>{:else}<span class="text-xs text-gray-500">根据你的订单与售后预约逐笔核对</span>{/if}
			<button
				type="submit"
				disabled={busy || !message.trim()}
				class="ml-auto flex items-center gap-2 rounded-lg px-4 py-2 text-sm bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 disabled:opacity-40"
				>{#if generating}<Spinner className="size-4" />{/if}{generating
					? '正在核对'
					: '生成调整建议'}</button
			>
		</div>
	</form>
	{#if error}<p role="alert" class="text-sm text-red-600 dark:text-red-400">{error}</p>{/if}
	{#if session}
		<div class="space-y-3">
			<p class="text-sm leading-6">{session.summary}</p>
			{#if session.questions.length}<div
					class="rounded-xl bg-gray-50 dark:bg-gray-850 p-4 text-sm space-y-2"
				>
					{#each session.questions as question}<p>{question}</p>{/each}
					<p class="text-xs text-gray-500">在上方补充说明后，重新生成建议。</p>
				</div>{/if}
			{#if session.dismissed}<p class="text-sm text-gray-500">
					建议已取消，已确认的订单和预约保持现状。
				</p>
			{:else if session.items.some((item) => item.decision === 'change')}<p
					class="text-xs text-gray-500"
				>
					勾选要调整的记录，逐笔核对表单并确认后才会生效。
				</p>{/if}
		</div>
		{#if !session.dismissed && session.items.some((item) => item.decision === 'change')}
			<div
				class="flex flex-wrap justify-end gap-2 border-t border-gray-100 dark:border-gray-850 pt-4"
			>
				<button
					disabled={busy}
					class="rounded-lg px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
					on:click={dismiss}>取消建议</button
				>
				<button
					disabled={busy || !chosen.length}
					class="rounded-lg px-4 py-2 text-sm bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 disabled:opacity-40"
					on:click={applySelected}>核对所选{chosen.length ? `（${chosen.length}）` : ''}</button
				>
			</div>
		{/if}
		<div class="divide-y divide-gray-100 dark:divide-gray-850">
			{#each visibleItems as item (key(item))}
				<article
					class="py-4 first:pt-0"
					aria-label={`${item.name} ${item.kind === 'orders' ? '订单' : '报修预约'} ${recordNumber(item.id)}`}
				>
					<div class="flex items-start gap-3">
						{#if selectable(item)}<input
								aria-label={`选择调整 ${item.model} ${recordNumber(item.id)}`}
								type="checkbox"
								bind:group={selected}
								value={key(item)}
								disabled={busy}
								class="mt-1 size-4 accent-gray-900 dark:accent-gray-100"
							/>{/if}
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap justify-between gap-2">
								<h2 class="text-sm font-medium">
									{item.name} · {item.kind === 'orders' ? '订单' : '报修预约'}
								</h2>
								<span class="text-xs text-gray-500"
									>{item.outcome !== '未变更'
										? item.outcome
										: item.decision === 'keep'
											? '保留原安排'
											: item.decision === 'clarify'
												? '待补充'
												: session.dismissed
													? '未变更'
													: '待确认'}</span
								>
							</div>
							<p class="text-xs text-gray-500 mt-1">
								{item.model} · {recordNumber(item.id)} · {item.status}
							</p>
							<div class="grid sm:grid-cols-2 gap-3 mt-3 text-sm">
								<div>
									<p class="text-xs text-gray-500 mb-1">原安排</p>
									<p>{item.before.date} {item.before.slot}</p>
									<p class="text-xs text-gray-500 mt-1">{item.before.service}</p>
								</div>
								{#if item.decision === 'change'}<div>
										<p class="text-xs text-gray-500 mb-1">建议日期</p>
										<p>{item.proposed.date} {item.proposed.slot}</p>
									</div>{/if}
							</div>
							<p class="text-sm text-gray-500 mt-3">{item.reason}</p>
							{#if item.current && item.outcome !== '未变更'}<p class="text-xs mt-2">
									当前记录：{item.current.date}
									{item.current.slot} · {item.current.service}
								</p>{/if}
						</div>
					</div>
				</article>
			{/each}
		</div>
		{#if !affectedItems.length}<p class="text-sm text-gray-500">
				没有需要调整的安排{retainedItems.length
					? `，现有 ${retainedItems.length} 条记录保持不变`
					: ''}。
			</p>{/if}
		{#if retainedItems.length}<button
				class="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 py-1"
				aria-expanded={showRetained}
				on:click={() => (showRetained = !showRetained)}
				>{showRetained ? '收起其余记录' : `查看其余 ${retainedItems.length} 条记录`}</button
			>{/if}
	{/if}
</div>
<ToolInteraction bind:this={interaction} />
