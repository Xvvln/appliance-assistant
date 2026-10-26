<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { socket } from '$lib/stores';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	type ToolEvent = {
		chat_id: string;
		message_id: string;
		data: { type: string; data: { code?: string; title?: string; message?: string } };
	};
	type EventReply = (result: unknown) => void;
	let operationId = '';
	let controller: AbortController | null = null;
	let cancelPending: (() => void) | null = null;
	let confirmReply: EventReply | null = null;
	let confirmTitle = '';
	let confirmMessage = '';
	let showConfirmation = false;
	let mounted = false;

	function answerConfirmation(confirmed: boolean) {
		const reply = confirmReply;
		showConfirmation = false;
		confirmReply = null;
		reply?.(confirmed);
	}

	function closePending() {
		cancelPending?.();
		cancelPending = null;
		showConfirmation = false;
		confirmReply = null;
		// Let the existing form cancel its promise and restore focus.
		for (const id of ['jiadian-service-dialog', 'jiadian-address-dialog']) {
			document.getElementById(id)?.dispatchEvent(new Event('cancel', { cancelable: true }));
		}
	}

	async function handleEvent(event: ToolEvent, callback?: EventReply) {
		if (
			!operationId ||
			event.chat_id !== `jiadian-records:${operationId}` ||
			event.message_id !== operationId ||
			!callback
		)
			return;
		const { type, data } = event.data;
		let answered = false;
		const reply: EventReply = (result) => {
			if (answered) return;
			answered = true;
			if (cancelPending === cancel) cancelPending = null;
			callback(result);
		};
		const cancel = () => reply(type === 'confirmation' ? false : { action: 'cancel' });
		cancelPending = cancel;
		if (type === 'confirmation') {
			confirmTitle = data.title ?? '确认操作';
			confirmMessage = data.message ?? '';
			confirmReply = reply;
			showConfirmation = true;
		} else if (type === 'execute' && data.code) {
			try {
				// Match the native chat handler for server-authored tool forms.
				const execute = new Function(
					`return (async () => { ${data.code} })()`
				) as () => Promise<unknown>;
				reply(await execute());
			} catch {
				reply({ error: '表单未能打开，请重试。' });
			}
		} else cancel();
	}

	export async function run<T>(
		request: (sessionId: string, operationId: string, signal: AbortSignal) => Promise<T>
	): Promise<T> {
		if (!mounted || !$socket?.connected || !$socket.id) {
			throw new Error('连接尚未就绪，请稍后重试');
		}
		if (operationId) throw new Error('请先完成当前操作');
		operationId = crypto.randomUUID();
		controller = new AbortController();
		try {
			return await request($socket.id, operationId, controller.signal);
		} finally {
			if (mounted) closePending();
			operationId = '';
			controller = null;
		}
	}

	onMount(() => {
		mounted = true;
		let detach = () => {};
		const unsubscribe = socket.subscribe((connection) => {
			detach();
			if (!connection) return;
			const disconnected = () => {
				if (!operationId) return;
				closePending();
				controller?.abort();
				toast.error('连接已断开，请刷新后重试');
			};
			connection.on('events', handleEvent);
			connection.on('disconnect', disconnected);
			detach = () => {
				connection.off('events', handleEvent);
				connection.off('disconnect', disconnected);
			};
		});
		return () => {
			mounted = false;
			if (operationId) closePending();
			controller?.abort();
			unsubscribe();
			detach();
		};
	});
</script>

<ConfirmDialog
	bind:show={showConfirmation}
	title={confirmTitle}
	cancelLabel="返回"
	confirmLabel="确认"
	on:confirm={() => answerConfirmation(true)}
	on:cancel={() => answerConfirmation(false)}
>
	<div class="text-sm text-gray-500 whitespace-pre-line break-words max-h-[60dvh] overflow-y-auto">
		{confirmMessage}
	</div>
</ConfirmDialog>
