<script lang="ts">
	import '../app.css';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import { page } from '$app/stores';

	let { children } = $props();

	const isChatPage = $derived($page.url.pathname === '/chat');
	const isUploadPage = $derived($page.url.pathname === '/upload');
	const isDocumentsPage = $derived($page.url.pathname === '/documents');

	// Page titles for non-chat pages
	const pageTitle = $derived(() => {
		const path = $page.url.pathname;
		switch (path) {
			case '/upload':
				return 'Upload';
			case '/documents':
				return 'Documents';
			case '/dashboard':
				return 'Dashboard';
			case '/settings':
				return 'Settings';
			default:
				return null;
		}
	});
</script>

<div class="min-h-screen bg-base-100 flex">
	<!-- Sidebar - always visible on all pages -->
	<ChatSidebar />

	<!-- Main content area -->
	<div class="flex-1 flex flex-col min-w-0">
		<!-- Global header for non-chat pages -->
		{#if !isChatPage}
			<header class="flex items-center justify-between border-b border-base-300 px-6 py-4">
				<div class="flex items-center gap-3">
					{#if isUploadPage}
						<a href="/documents" class="btn btn-ghost btn-sm btn-square" title="Back to Documents">
							<svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
							</svg>
						</a>
					{/if}
					<h1 class="text-lg font-semibold">{pageTitle()}</h1>
				</div>
				{#if isDocumentsPage}
					<div class="flex items-center gap-1">
						<div class="tooltip tooltip-left" data-tip="Upload files">
							<a
								href="/upload?trigger=files"
								class="btn btn-sm btn-square btn-action"
								aria-label="Upload files"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									class="h-5 w-5"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="1.5"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M7 21h10a2 2 0 002-2V9l-5-5H7a2 2 0 00-2 2v12a2 2 0 002 2z"
									/>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M12 17v-5m0 0l-2 2m2-2l2 2"
									/>
								</svg>
							</a>
						</div>
						<div class="tooltip tooltip-left" data-tip="Upload directory">
							<a
								href="/upload?trigger=directory"
								class="btn btn-sm btn-square btn-action"
								aria-label="Upload directory"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									class="h-5 w-5"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="1.5"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
									/>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M12 16v-4m0 0l-2 2m2-2l2 2"
									/>
								</svg>
							</a>
						</div>
					</div>
				{/if}
			</header>
		{/if}
		<main class="flex-1 {isChatPage ? '' : 'container mx-auto p-4'}">
			{@render children()}
		</main>
	</div>
</div>
