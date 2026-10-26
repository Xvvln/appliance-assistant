<script lang="ts">
	import { onMount } from 'svelte';
	import { getCatalog, type Product } from '$lib/apis/jiadian';
	import { createPreview, getPreview, listPreviews, previewFile, type PreviewSession } from '$lib/apis/assistant-preview';
	import Spinner from '$lib/components/common/Spinner.svelte';
	let products: Product[] = [];
	let sessions: PreviewSession[] = [];
	let selected: PreviewSession | null = null;
	let model = '';
	let instruction = '';
	let photo = '';
	let photoName = '';
	let originalUrl = '';
	let resultUrl = '';
	let loadedOriginal = '';
	let loadedResult = '';
	let width: number | undefined;
	let height: number | undefined;
	let depth: number | undefined;
	let loading = true;
	let submitting = false;
	let error = '';
	let mounted = false;
	let rpm = 1;
	let poll: ReturnType<typeof setTimeout> | undefined;
	$: pending = selected?.status === 'queued' || selected?.status === 'generating';
	const field = 'w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2.5 text-sm';

	async function display(state: PreviewSession) {
		selected = state;
		sessions = sessions.map((item) => item.id === state.id ? state : item);
		model = state.model;
		instruction = state.instruction;
		width = state.dimensions?.width; height = state.dimensions?.height; depth = state.dimensions?.depth;
		if (state.original.id !== loadedOriginal) {
			const blob = await previewFile(state.original.url);
			if (!mounted || selected?.id !== state.id) return;
			if (originalUrl) URL.revokeObjectURL(originalUrl);
			originalUrl = URL.createObjectURL(blob); loadedOriginal = state.original.id;
		}
		if (state.image && state.image.id !== loadedResult) {
			const blob = await previewFile(state.image.url);
			if (!mounted || selected?.id !== state.id) return;
			if (resultUrl) URL.revokeObjectURL(resultUrl);
			resultUrl = URL.createObjectURL(blob); loadedResult = state.image.id;
		} else if (!state.image) {
			if (resultUrl) URL.revokeObjectURL(resultUrl);
			resultUrl = ''; loadedResult = '';
		}
		clearTimeout(poll);
		if (state.status === 'queued' || state.status === 'generating') {
			poll = setTimeout(async () => {
				try { const updated = await getPreview(state.id); if (mounted && selected?.id === state.id) await display(updated); }
				catch (e) { if (mounted) error = e instanceof Error ? e.message : '暂时无法查看进度'; }
			}, 2500);
		}
	}
	async function upload(event: Event) {
		const file = (event.target as HTMLInputElement).files?.[0];
		if (!file) return;
		if (file.size > 10 * 1024 * 1024) { error = '请选择小于 10 MB 的图片'; return; }
		photo = await new Promise<string>((resolve, reject) => {
			const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(file);
		});
		photoName = file.name; error = '';
	}
	async function generate() {
		if (submitting || pending) return;
		error = ''; submitting = true;
		try {
			let source = photo;
			if (!source && selected) {
				const blob = await previewFile(selected.original.url);
				source = await new Promise<string>((resolve) => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.readAsDataURL(blob); });
			}
			if (!source || !model) throw new Error('请先选择产品并上传房间照片');
			const state = await createPreview({ model, image: source, instruction, request_id: crypto.randomUUID(),
				...(width && height && depth ? { dimensions: { width, height, depth } } : {}) });
			if (!mounted) return;
			photo = ''; photoName = ''; sessions = [state, ...sessions]; await display(state);
		} catch (e) { if (mounted) error = e instanceof Error ? e.message : '未能开始生成，请重试'; }
		finally { if (mounted) submitting = false; }
	}
	onMount(() => {
		mounted = true;
		void (async () => {
			try {
				const [catalog, history] = await Promise.all([getCatalog(), listPreviews()]);
				if (!mounted) return;
				products = catalog.products; sessions = history.sessions; rpm = history.requests_per_minute;
				if (sessions[0]) await display(sessions[0]);
			} catch (e) { if (mounted) error = e instanceof Error ? e.message : '暂时无法加载'; }
			finally { if (mounted) loading = false; }
		})();
		return () => { mounted = false; clearTimeout(poll); if (originalUrl) URL.revokeObjectURL(originalUrl); if (resultUrl) URL.revokeObjectURL(resultUrl); };
	});
</script>

{#if loading}<div class="flex justify-center py-12"><Spinner /></div>{:else}
	<div class="space-y-6">
		<p class="text-sm text-gray-500">上传房间照片，看看所选家电放进家里的样子。</p>
		<div class="grid gap-5 md:grid-cols-2">
			<label class="space-y-2 text-sm"><span>选择产品</span><select class={field} bind:value={model} disabled={pending || submitting}>
				<option value="" disabled>请选择产品</option>{#each products as p}<option value={p.model}>{p.category} · {p.name}（{p.model}）</option>{/each}
			</select></label>
			<label class="space-y-2 text-sm"><span>房间照片</span><input type="file" accept="image/jpeg,image/png,image/webp" on:change={upload} disabled={pending || submitting} class="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-gray-100 file:px-3 file:py-2.5 dark:file:bg-gray-850" />
				{#if photoName}<span class="block text-xs text-gray-500">{photoName}</span>{/if}
			</label>
		</div>
		{#if photo}<img src={photo} alt="待生成的房间照片" class="max-h-52 rounded-lg object-contain" />{/if}
		<label class="block space-y-2 text-sm"><span>摆放想法</span><textarea class={field} rows="2" maxlength="1500" bind:value={instruction} disabled={pending || submitting} placeholder="例如：放在左侧靠墙的位置，保留原来的柜子和装修风格"></textarea></label>
		<details class="text-sm"><summary class="cursor-pointer py-2">核对预留空间（可选）</summary>
			<p class="text-xs text-gray-500 mt-2">填写实测尺寸；图片中的比例不能作为安装依据。</p>
			<div class="grid grid-cols-3 gap-3 mt-3">
				<label class="space-y-2"><span>宽（mm）</span><input class={field} type="number" min="1" bind:value={width} disabled={pending || submitting} /></label>
				<label class="space-y-2"><span>高（mm）</span><input class={field} type="number" min="1" bind:value={height} disabled={pending || submitting} /></label>
				<label class="space-y-2"><span>深（mm）</span><input class={field} type="number" min="1" bind:value={depth} disabled={pending || submitting} /></label>
			</div>
		</details>
		<div class="flex flex-wrap items-center gap-4">
			<button class="rounded-lg bg-gray-900 px-4 py-2.5 text-sm text-white dark:bg-gray-100 dark:text-gray-900 disabled:opacity-40" disabled={pending || submitting || !model || (!photo && !selected)} on:click={generate}>{submitting ? '正在提交…' : pending ? selected?.status === 'queued' ? '等待生成…' : '正在生成…' : '生成预览'}</button>
			<span class="text-xs text-gray-500">每分钟最多 {rpm} 张，按顺序生成</span>
		</div>
		{#if error}<p role="alert" class="text-sm text-red-600 dark:text-red-400">{error}</p>{/if}
		{#if selected}
			<div class="border-t border-gray-100 dark:border-gray-850 pt-5 space-y-4">
				{#if sessions.length > 1}<label class="flex items-center gap-3 text-sm"><span class="shrink-0">历史预览</span><select class={field} value={selected.id} disabled={pending || submitting} on:change={(e) => { const item = sessions.find(s => s.id === e.currentTarget.value); if (item) { photo = ''; void display(item); } }}>{#each sessions as item}<option value={item.id}>{item.name} · {item.instruction || '空间预览'}</option>{/each}</select></label>{/if}
				<div class="grid gap-4 md:grid-cols-2">
					<figure><figcaption class="text-sm mb-2">原始空间</figcaption>{#if originalUrl}<img src={originalUrl} alt="原始房间" class="w-full rounded-lg object-contain max-h-[450px]" />{/if}</figure>
					<figure><figcaption class="text-sm mb-2">{selected.name} · 外观参考</figcaption>
						{#if resultUrl}<img src={resultUrl} alt={`${selected.name}放入房间后的外观预览`} class="w-full rounded-lg object-contain max-h-[450px]" />
						{:else}<div class="flex flex-col items-center justify-center gap-3 min-h-48 bg-gray-50 dark:bg-gray-850 rounded-lg text-sm text-gray-500" aria-live="polite">
							{#if pending}<Spinner />{selected.status === 'queued' ? '已加入队列，轮到后自动开始' : '正在处理光线和摆放效果…'}{:else}{selected.error || '尚未生成图片'}{/if}
						</div>{/if}
					</figure>
				</div>
				{#if resultUrl}<a href={resultUrl} download={`${selected.model}-空间预览.png`} class="inline-block text-sm underline underline-offset-4">下载预览图</a>{/if}
				{#if selected.fit.checks}<div class="text-sm space-y-2"><p class="font-medium">{selected.fit.status}</p>{#each selected.fit.checks as check}<p class="text-gray-500">{check.label}：实测 {check.measured_mm} mm，资料要求 {check.required_mm} mm，{check.difference_mm >= 0 ? '余量' : '还差'} {Math.abs(check.difference_mm)} mm</p>{/each}<p class="text-xs text-gray-500">{selected.fit.message}</p></div>{/if}
				<p class="text-xs text-gray-500">图片为 AI 生成的外观参考，实际外观及安装条件以产品资料和现场核对为准。</p>
			</div>
		{/if}
	</div>
{/if}
