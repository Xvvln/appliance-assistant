<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { getCatalog, getRecords, type Product, type OrderRecord } from '$lib/apis/jiadian';
	import {
		getGuideSessions, getGuideSession, startGuidance, continueGuidance,
		type GuideSession, type GuideAction
	} from '$lib/apis/assistant-guidance';

	let products: Product[] = [];
	let orders: OrderRecord[] = [];
	let sessions: GuideSession[] = [];
	let current: GuideSession | null = null;
	let selection = '';
	let task = '';
	let feedback = '';
	let images: string[] = [];
	let loading = true;
	let busy = false;
	let uploading = false;
	let error = '';
	let mounted = false;
	const actionLabels: Record<GuideAction, string> = {
		completed: '这一步已做完', not_found: '没有找到', different: '情况不一样',
		message: '补充了情况', resolved: '已确认目标完成'
	};
	$: currentProduct = products.find((product) => product.model === current?.model);
	$: chosenOrder = selection.startsWith('order:')
		? orders.find((order) => order.order_id === selection.slice(6)) : undefined;
	$: chosenModel = chosenOrder?.model ?? (selection.startsWith('model:') ? selection.slice(6) : '');

	async function initialize() {
		loading = true;
		error = '';
		try {
			const [catalog, records, saved] = await Promise.all([getCatalog(), getRecords(), getGuideSessions()]);
			if (!mounted) return;
			products = catalog.products;
			orders = records.orders.filter((order) => order.status !== '已取消');
			sessions = saved.sessions;
			current = sessions.find((session) => session.status === 'active') ?? sessions[0] ?? null;
		} catch (cause) {
			if (mounted) error = cause instanceof Error ? cause.message : '暂时无法加载，请重试。';
		} finally {
			if (mounted) loading = false;
		}
	}

	function remember(session: GuideSession) {
		current = session;
		sessions = [session, ...sessions.filter((item) => item.id !== session.id)];
		images = [];
		feedback = '';
	}

	async function start() {
		if (busy || uploading || !chosenModel || !task.trim()) return;
		busy = true;
		error = '';
		try {
			const result = await startGuidance({ model: chosenModel, order_id: chosenOrder?.order_id, task: task.trim(), images });
			if (mounted) remember(result);
		} catch (cause) {
			if (mounted) error = cause instanceof Error ? cause.message : '暂时无法开始，请重试。';
		} finally {
			if (mounted) busy = false;
		}
	}

	async function respond(action: GuideAction) {
		if (!current || busy || uploading) return;
		busy = true;
		error = '';
		try {
			const result = await continueGuidance(current.id, { action, feedback: feedback.trim(), images });
			if (mounted) remember(result);
		} catch (cause) {
			if (mounted) error = cause instanceof Error ? cause.message : '暂时无法继续，请重试。';
		} finally {
			if (mounted) busy = false;
		}
	}

	async function resume(event: Event) {
		const id = (event.currentTarget as HTMLSelectElement).value;
		if (!id || busy) return;
		busy = true;
		error = '';
		try {
			const result = await getGuideSession(id);
			if (mounted) remember(result);
		} catch (cause) {
			if (mounted) error = cause instanceof Error ? cause.message : '暂时无法打开记录。';
		} finally {
			if (mounted) busy = false;
		}
	}

	function newOperation() {
		current = null;
		selection = '';
		task = '';
		feedback = '';
		images = [];
		error = '';
	}

	async function upload(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const files = Array.from(input.files ?? []);
		input.value = '';
		if (images.length + files.length > 3) { toast.error('每次最多上传 3 张图片'); return; }
		if (files.some((file) => !['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024)) {
			toast.error('请上传 JPG、PNG 或 WebP 图片，每张不超过 5 MB'); return;
		}
		uploading = true;
		try {
			const added = await Promise.all(files.map((file) => new Promise<string>((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('图片读取失败'));
				reader.onerror = () => reject(new Error('图片读取失败'));
				reader.readAsDataURL(file);
			})));
			if (mounted) images = [...images, ...added];
		} catch { if (mounted) toast.error('图片读取失败，请重试'); }
		finally { if (mounted) uploading = false; }
	}

	function requestService() {
		if (!current) return;
		const tried = current.history.map((item, index) =>
			`${index + 1}. ${item.step.title}：${item.step.instruction}\n用户反馈：${actionLabels[item.action]}${item.feedback ? '；' + item.feedback : ''}\n观察：${item.step.observation}`
		).join('\n');
		const summary = `我需要为 ${current.model}${current.order_id ? '（订单 ' + current.order_id + '）' : ''}预约报修。\n想解决的问题：${current.task}\n已尝试和确认的内容：\n${tried || '尚未完成操作'}\n当前情况：${current.current_step.observation}${feedback.trim() ? '\n补充：' + feedback.trim() : ''}\n请保留上述排查结果，核对机器后继续现有预约流程；预约时间和地址由我选择，提交前让我确认。`;
		void goto('/?' + new URLSearchParams({ models: 'jiadian-assistant', q: summary }));
	}

	onMount(() => {
		mounted = true;
		void initialize();
		return () => { mounted = false; };
	});
</script>

<div class="max-w-3xl mx-auto pb-8">
	{#if loading}<div class="flex justify-center py-16"><Spinner /></div>
	{:else}
		{#if sessions.length}
			<div class="flex flex-wrap items-center gap-3 mb-6">
				<select aria-label="操作记录" value={current?.id ?? ''} disabled={busy || uploading} on:change={resume}
					class="min-w-0 flex-1 bg-gray-50 dark:bg-gray-850 rounded-xl p-3 text-sm">
					<option value="" disabled>打开之前的操作</option>
					{#each sessions as session}<option value={session.id}>{session.model} · {session.task} {session.status === 'completed' ? '（已完成）' : ''}</option>{/each}
				</select>
				<button class="px-3 py-2 text-sm rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40"
					disabled={busy || uploading} on:click={newOperation}>开始新的操作</button>
			</div>
		{/if}
		{#if !current}
			<form on:submit|preventDefault={start} class="space-y-5">
				<div><label for="guide-appliance" class="block text-sm font-medium mb-2">选择机器</label>
					<select id="guide-appliance" required bind:value={selection} disabled={busy}
						class="w-full bg-gray-50 dark:bg-gray-850 rounded-xl p-3 text-sm">
						<option value="" disabled>请选择准确型号或已购订单</option>
						{#if orders.length}<optgroup label="已购订单">{#each orders as order}<option value={`order:${order.order_id}`}>{order.model} · {order.order_id.replace(/^DEMO-/, '')}</option>{/each}</optgroup>{/if}
						<optgroup label="产品型号">{#each products as product}<option value={`model:${product.model}`}>{product.name} · {product.model}</option>{/each}</optgroup>
					</select>
				</div>
				<div><label for="guide-task" class="block text-sm font-medium mb-2">想完成什么操作？</label>
					<textarea id="guide-task" rows="3" maxlength="2000" required bind:value={task} disabled={busy}
						placeholder="例如：第一次使用自动投放，想跟着指引操作"
						class="w-full resize-y bg-gray-50 dark:bg-gray-850 rounded-xl p-3 text-sm outline-none"></textarea>
				</div>
				<div class="flex justify-end"><button type="submit" disabled={busy || uploading || !chosenModel || !task.trim()}
					class="rounded-xl px-4 py-2.5 bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 text-sm disabled:opacity-40">开始指导</button></div>
			</form>
		{:else}
			<div class="flex items-start gap-3 mb-5">
				{#if currentProduct}<img src={`/static/jiadian/products/${current.model}.png`} alt={currentProduct.name} class="size-14 rounded-lg object-contain bg-white p-1" />{/if}
				<div class="min-w-0"><p class="font-medium break-words">{current.task}</p>
					<p class="text-xs text-gray-500 mt-1">{currentProduct?.name ?? current.model} · {current.model}</p></div>
			</div>
			{#if current.history.length}
				<details class="border-b border-gray-100 dark:border-gray-850 pb-4 mb-5">
					<summary class="text-sm text-gray-500 cursor-pointer">查看操作记录（{current.history.length}）</summary>
					<div class="space-y-4 mt-4">{#each current.history as entry, index}
						<div class="text-sm"><p class="font-medium">{index + 1}. {entry.step.title}</p>
							<p class="mt-1 whitespace-pre-line text-gray-600 dark:text-gray-400">{entry.step.instruction}</p>
							<p class="mt-2 text-xs text-gray-500">{actionLabels[entry.action]}{entry.feedback ? ' · ' + entry.feedback : ''}{entry.image_count ? ` · 补充了 ${entry.image_count} 张图片` : ''}</p>
						</div>
					{/each}</div>
				</details>
			{/if}
			{#if current.status === 'completed'}
				<div class="py-6"><h2 class="font-medium">操作已完成</h2><p class="text-sm text-gray-500 mt-2">已保存你确认的结果，之后可以继续查看。</p></div>
			{:else}
				<article class="space-y-4">
					<h2 class="text-lg font-medium">{current.current_step.title}</h2>
					<p class="text-sm text-gray-500 whitespace-pre-line">{current.current_step.observation}</p>
					<p class="text-sm leading-6 whitespace-pre-line">{current.current_step.instruction}</p>
					<p class="text-sm text-gray-600 dark:text-gray-400 whitespace-pre-line">{current.current_step.verification}</p>
					<details class="text-sm"><summary class="cursor-pointer text-gray-500">查看说明书依据</summary>
						<blockquote class="border-l-2 border-gray-200 dark:border-gray-700 pl-3 mt-3 whitespace-pre-line text-gray-500">{current.current_step.quote}</blockquote>
						<a class="inline-block text-xs mt-2 underline text-gray-500" href={`/workspace/knowledge/washer-cloud?doc=${encodeURIComponent(current.model + '_说明书')}`}>打开本型号说明书</a>
					</details>
				</article>
				<div class="flex flex-wrap gap-2 mt-6">
					<button disabled={busy || uploading} on:click={() => respond('completed')} class="rounded-xl px-4 py-2.5 bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 text-sm disabled:opacity-40">这一步做完了</button>
					<button disabled={busy || uploading} on:click={() => respond('not_found')} class="rounded-xl px-4 py-2.5 bg-gray-100 dark:bg-gray-850 text-sm disabled:opacity-40">找不到</button>
					<button disabled={busy || uploading} on:click={() => respond('different')} class="rounded-xl px-4 py-2.5 bg-gray-100 dark:bg-gray-850 text-sm disabled:opacity-40">情况不一样</button>
				</div>
				<div class="mt-5"><label for="guide-feedback" class="block text-sm mb-2">补充情况</label>
					<textarea id="guide-feedback" rows="2" maxlength="2000" bind:value={feedback} disabled={busy} placeholder="也可以直接提问，或补拍看不清的局部"
						class="w-full resize-y bg-gray-50 dark:bg-gray-850 rounded-xl p-3 text-sm outline-none"></textarea>
					<button disabled={busy || uploading || (!feedback.trim() && !images.length)} on:click={() => respond('message')}
						class="mt-2 px-3 py-2 text-sm rounded-lg bg-gray-100 dark:bg-gray-850 disabled:opacity-40">发送补充</button>
				</div>
				<div class="flex flex-wrap justify-between gap-3 border-t border-gray-100 dark:border-gray-850 mt-6 pt-4">
					<button disabled={busy || uploading} on:click={() => respond('resolved')} class="text-sm px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40">我确认目标已完成</button>
					<button disabled={busy || uploading} on:click={requestService} class="text-sm px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40">{current.current_step.needs_service ? '预约报修' : '仍未解决，预约报修'}</button>
				</div>
			{/if}
		{/if}
		{#if !current || current.status === 'active'}
			<div class="mt-5"><label class="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer bg-gray-100 dark:bg-gray-850">
				上传现场照片<input type="file" class="sr-only" accept="image/jpeg,image/png,image/webp" multiple disabled={busy || uploading} on:change={upload} />
			</label><span class="text-xs text-gray-500 ml-2">可拍面板或需要查看的局部，最多 3 张</span></div>
			{#if images.length}<div class="flex flex-wrap gap-3 mt-3">{#each images as image, index}<div>
				<img src={image} alt={`待发送的现场照片 ${index + 1}`} class="size-24 object-cover rounded-lg" />
				<button class="text-xs text-gray-500 py-2" disabled={busy} on:click={() => images = images.filter((_, item) => item !== index)}>移除照片 {index + 1}</button>
			</div>{/each}</div>{/if}
		{/if}
		{#if busy}<div role="status" class="flex items-center gap-2 py-5 text-sm text-gray-500"><Spinner className="size-4" />正在核对说明书和本次反馈…</div>{/if}
		{#if error}<div role="alert" class="text-sm text-red-600 dark:text-red-400 mt-4">{error}</div>{/if}
	{/if}
</div>
