<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import {
		fetchSystemMetrics,
		fetchEvaluationSummary,
		type SystemMetrics,
		type EvaluationSummary
	} from '$lib/api';
	import DashboardTabs from '$lib/components/dashboard/DashboardTabs.svelte';
	import ComparisonTab from '$lib/components/dashboard/ComparisonTab.svelte';
	import HistoryTab from '$lib/components/dashboard/HistoryTab.svelte';
	import ConfigTab from '$lib/components/dashboard/ConfigTab.svelte';
	import SystemHealthTab from '$lib/components/dashboard/SystemHealthTab.svelte';

	let metrics = $state<SystemMetrics | null>(null);
	let evalSummary = $state<EvaluationSummary | null>(null);
	let isLoading = $state(true);
	let error = $state<string | null>(null);
	let autoRefresh = $state(true);
	let refreshInterval: number | null = null;

	// Tab state - read from URL or default to 'comparison'
	let activeTab = $state<string>('comparison');

	const tabs = [
		{ id: 'comparison', label: 'Comparison', icon: 'chart' },
		{ id: 'history', label: 'History', icon: 'history' },
		{ id: 'config', label: 'Config', icon: 'config' },
		{ id: 'health', label: 'System Health', icon: 'health' }
	];

	onMount(() => {
		// Read tab from URL
		const urlTab = $page.url.searchParams.get('tab');
		if (urlTab && tabs.some((t) => t.id === urlTab)) {
			activeTab = urlTab;
		}

		loadAll();
		startAutoRefresh();
		return () => stopAutoRefresh();
	});

	function handleTabChange(tabId: string) {
		activeTab = tabId;
		// Update URL without navigation
		const url = new URL(window.location.href);
		url.searchParams.set('tab', tabId);
		goto(url.pathname + url.search, { replaceState: true, keepFocus: true });
	}

	function startAutoRefresh() {
		if (autoRefresh && !refreshInterval) {
			refreshInterval = window.setInterval(() => loadAll(), 30000);
		}
	}

	function stopAutoRefresh() {
		if (refreshInterval) {
			clearInterval(refreshInterval);
			refreshInterval = null;
		}
	}

	function toggleAutoRefresh() {
		autoRefresh = !autoRefresh;
		if (autoRefresh) {
			startAutoRefresh();
		} else {
			stopAutoRefresh();
		}
	}

	async function loadAll() {
		if (!autoRefresh && !isLoading) isLoading = true;
		error = null;
		try {
			const [m, e] = await Promise.all([
				fetchSystemMetrics(),
				fetchEvaluationSummary().catch(() => null)
			]);
			metrics = m;
			evalSummary = e;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load data';
		} finally {
			isLoading = false;
		}
	}
</script>

{#if isLoading && !metrics}
	<div class="flex items-center justify-center h-[calc(100vh-200px)]">
		<span class="loading loading-spinner loading-lg"></span>
	</div>
{:else if error && !metrics}
	<div class="flex flex-col items-center justify-center h-[calc(100vh-200px)] gap-4">
		<div class="alert alert-error max-w-md">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-5 w-5"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
				/>
			</svg>
			<span>{error}</span>
		</div>
		<button class="btn btn-primary btn-sm" onclick={loadAll}>Retry</button>
	</div>
{:else if metrics}
	<div class="flex flex-col gap-3">
		<!-- Header Bar -->
		<div class="bg-base-200 rounded px-3 py-2 flex items-center justify-between text-xs">
			<div class="flex items-center gap-3">
				<span class="font-bold text-sm">{metrics.system_name}</span>
				<span class="text-base-content/50">v{metrics.version}</span>
				<div class="divider divider-horizontal mx-0 h-4"></div>
				<span class="flex items-center gap-1">
					<span
						class="h-2 w-2 rounded-full {metrics.health_status === 'healthy'
							? 'bg-success animate-pulse'
							: 'bg-error'}"
					></span>
					<span class="capitalize">{metrics.health_status}</span>
				</span>
				<div class="divider divider-horizontal mx-0 h-4"></div>
				<span><strong>{metrics.document_count}</strong> docs</span>
				<span><strong>{metrics.chunk_count.toLocaleString()}</strong> chunks</span>
			</div>
			<div class="flex items-center gap-1">
				<span class="text-base-content/50"
					>{new Date(metrics.timestamp).toLocaleTimeString()}</span
				>
				<button
					class="btn btn-ghost btn-xs"
					onclick={toggleAutoRefresh}
					title={autoRefresh ? 'Auto-refresh ON (30s)' : 'Auto-refresh OFF'}
				>
					{#if autoRefresh}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-3.5 w-3.5 text-success"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
							/>
						</svg>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-3.5 w-3.5 text-base-content/50"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"
							/>
						</svg>
					{/if}
				</button>
				<button
					class="btn btn-ghost btn-xs"
					onclick={loadAll}
					disabled={isLoading}
					aria-label="Refresh"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-3.5 w-3.5 {isLoading ? 'animate-spin' : ''}"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
						/>
					</svg>
				</button>
			</div>
		</div>

		<!-- Services Status (compact) -->
		{#if Object.keys(metrics.component_status).length > 0}
			<div class="flex items-center gap-2 px-1">
				<span class="text-xs text-base-content/50">Services:</span>
				{#each Object.entries(metrics.component_status) as [name, status]}
					<div class="tooltip tooltip-bottom" data-tip="{name}: {status}">
						<span
							class="flex items-center gap-1 text-xs bg-base-200 rounded px-1.5 py-0.5"
						>
							<span
								class="h-1.5 w-1.5 rounded-full {status === 'healthy' ||
								status === 'available'
									? 'bg-success'
									: 'bg-error'}"
							></span>
							<span class="capitalize">{name}</span>
						</span>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Tabbed Content -->
		<DashboardTabs {activeTab} onTabChange={handleTabChange} {tabs}>
			{#if activeTab === 'comparison'}
				<ComparisonTab {evalSummary} onRefresh={loadAll} />
			{:else if activeTab === 'history'}
				<HistoryTab />
			{:else if activeTab === 'config'}
				<ConfigTab />
			{:else if activeTab === 'health'}
				<SystemHealthTab {metrics} />
			{/if}
		</DashboardTabs>
	</div>
{/if}
