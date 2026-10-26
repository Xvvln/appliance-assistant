<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { WEBUI_NAME, showSidebar, mobile } from '$lib/stores';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import GuidePanel from '$lib/components/jiadian/assistant/GuidePanel.svelte';
	import PlanPanel from '$lib/components/jiadian/assistant/PlanPanel.svelte';
	import ChangePanel from '$lib/components/jiadian/assistant/ChangePanel.svelte';
	import PreviewPanel from '$lib/components/jiadian/assistant/PreviewPanel.svelte';
	const tabs = [
		{ id: 'guide', label: '陪我操作' },
		{ id: 'plan', label: '一起做方案' },
		{ id: 'changes', label: '计划调整' },
		{ id: 'preview', label: '空间预览' }
	];
	$: selected = tabs.some((tab) => tab.id === $page.url.searchParams.get('tool'))
		? $page.url.searchParams.get('tool')
		: 'guide';
</script>

<svelte:head><title>生活助手 / {$WEBUI_NAME}</title></svelte:head>
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
		<h1 class="text-lg font-medium">生活助手</h1>
	</header>
	<main class="flex-1 min-h-0 overflow-y-auto px-4 pb-8">
		<div class="max-w-4xl mx-auto">
			<nav
				aria-label="生活助手功能"
				class="flex gap-5 overflow-x-auto border-b border-gray-100 dark:border-gray-850 mb-6"
			>
				{#each tabs as tab}<a
						href={`/assistant?tool=${tab.id}`}
						aria-current={selected === tab.id ? 'page' : undefined}
						class="shrink-0 py-3 border-b-2 text-sm {selected === tab.id
							? 'border-gray-900 dark:border-gray-100 font-medium'
							: 'border-transparent text-gray-500'}"
						on:click|preventDefault={() => goto(`/assistant?tool=${tab.id}`, { noScroll: true })}
						>{tab.label}</a
					>{/each}
			</nav>
			{#if selected === 'guide'}<GuidePanel />
			{:else if selected === 'plan'}<PlanPanel />
			{:else if selected === 'changes'}<ChangePanel />
			{:else}<PreviewPanel />{/if}
		</div>
	</main>
</div>
