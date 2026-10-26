<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME } from '$lib/stores';
	import {
		getCloudKnowledge,
		getProductDocument,
		type CloudKnowledge,
		type ProductDocument
	} from '$lib/apis/jiadian';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	let knowledge: CloudKnowledge | null = null;
	let query = '';
	let active: ProductDocument | null = null;
	let content = '';
	let error = '';
	let loading = true;
	let documentLoading = false;
	let requestId = 0;
	$: docs =
		knowledge?.documents.filter((d) =>
			`${d.model} ${d.kind}`.toLowerCase().includes(query.toLowerCase())
		) ?? [];
	async function open(doc: ProductDocument) {
		active = doc;
		content = '';
		error = '';
		documentLoading = true;
		const current = ++requestId;
		try {
			const result = await getProductDocument(doc.id);
			if (current === requestId) content = result.content;
		} catch (e) {
			if (current === requestId) error = e instanceof Error ? e.message : '加载失败';
		} finally {
			if (current === requestId) documentLoading = false;
		}
	}
	async function load() {
		loading = true;
		error = '';
		try {
			knowledge = await getCloudKnowledge();
			const doc = knowledge.documents.find((d) => d.id === $page.url.searchParams.get('doc'));
			if (doc) await open(doc);
		} catch (e) {
			error = e instanceof Error ? e.message : '加载失败';
		} finally {
			loading = false;
		}
	}
	onMount(load);
</script>

<svelte:head><title>家电产品资料 / {$WEBUI_NAME}</title></svelte:head>
<div class="flex-1 min-h-0 flex flex-col px-4 pb-4 overflow-y-auto">
	<div class="py-4">
		<button
			class="text-xs text-gray-500 hover:underline mb-3"
			on:click={() => goto('/workspace/knowledge')}>返回知识库</button
		>
		<h1 class="text-xl font-semibold">家电产品资料</h1>
		<p class="text-xs text-gray-500 mt-1">{knowledge?.file_count ?? 0} 份产品参数与使用说明书</p>
	</div>
	{#if loading}<div class="flex justify-center py-12"><Spinner /></div>
	{:else}<div class="flex flex-col md:flex-row flex-1 min-h-0 gap-6">
			<aside class="w-full md:w-64 shrink-0 md:overflow-y-auto">
				<div class="flex items-center gap-2 bg-gray-50 dark:bg-gray-850 rounded-xl px-3 mb-3">
					<Search className="size-4 text-gray-500" /><input
						aria-label="搜索资料"
						placeholder="搜索型号或资料"
						class="bg-transparent py-3 text-sm w-full outline-none"
						bind:value={query}
					/>
				</div>
				<div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-1 gap-1">
					{#each docs as doc}<button
							class="text-left rounded-lg p-3 text-sm hover:bg-gray-100 dark:hover:bg-gray-850 {active?.id ===
							doc.id
								? 'bg-gray-100 dark:bg-gray-850'
								: ''}"
							aria-current={active?.id === doc.id ? 'page' : undefined}
							on:click={() => open(doc)}
							><span class="block font-medium">{doc.model}</span><span class="text-xs text-gray-500"
								>{doc.kind}</span
							></button
						>{/each}
				</div>
				{#if !docs.length}<p class="text-sm text-gray-500 py-6">没有匹配的资料。</p>{/if}
			</aside>
			<section aria-label="资料内容" class="min-w-0 flex-1 md:overflow-y-auto px-2 pb-8">
				{#if error}<p role="alert" class="text-sm">
						{error}<button class="ml-3 underline" on:click={() => (active ? open(active) : load())}
							>重试</button
						>
					</p>
				{:else if documentLoading}<div class="flex justify-center py-12"><Spinner /></div>
				{:else if active}<div class="prose dark:prose-invert max-w-none text-sm">
						<Markdown id={`knowledge-${active.id}`} {content} />
					</div>
				{:else}<p class="text-sm text-gray-500 py-12 text-center">选择一份资料查看内容。</p>{/if}
			</section>
		</div>{/if}
</div>
