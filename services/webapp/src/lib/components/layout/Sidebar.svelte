<script lang="ts">
	import { page } from '$app/stores';
	import { FileText, MessageSquare, LayoutDashboard, PanelLeftClose, PanelLeft } from 'lucide-svelte';
	import { sidebar } from '$lib/stores/sidebar.svelte';
	import SidebarItem from './SidebarItem.svelte';
	import ThemeToggle from './ThemeToggle.svelte';

	const navItems = [
		{ href: '/documents', icon: FileText, label: 'Documents' },
		{ href: '/chat', icon: MessageSquare, label: 'Chat' },
		{ href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' }
	];
</script>

<aside
	class="fixed left-0 top-0 h-full bg-sidebar-bg flex flex-col transition-all duration-200 z-50"
	class:w-sidebar-expanded={!sidebar.collapsed}
	class:w-sidebar-collapsed={sidebar.collapsed}
>
	<!-- Logo area -->
	<div class="h-16 flex items-center px-4 border-b border-sidebar-hover">
		{#if sidebar.collapsed}
			<span class="text-xl font-bold text-white mx-auto">R</span>
		{:else}
			<span class="text-xl font-bold text-white">RAG System</span>
		{/if}
	</div>

	<!-- Navigation -->
	<nav class="flex-1 p-3 space-y-1">
		{#each navItems as item}
			<SidebarItem
				href={item.href}
				icon={item.icon}
				label={item.label}
				active={$page.url.pathname === item.href || ($page.url.pathname === '/' && item.href === '/documents')}
				collapsed={sidebar.collapsed}
			/>
		{/each}
	</nav>

	<!-- Bottom section -->
	<div class="p-3 border-t border-sidebar-hover space-y-1">
		<ThemeToggle collapsed={sidebar.collapsed} />

		<button
			onclick={() => sidebar.toggle()}
			class="flex items-center gap-3 w-full px-3 py-2 rounded-lg transition-colors
						 text-sidebar-text hover:bg-sidebar-hover"
			title={sidebar.collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
		>
			{#if sidebar.collapsed}
				<PanelLeft class="w-5 h-5 shrink-0" />
			{:else}
				<PanelLeftClose class="w-5 h-5 shrink-0" />
				<span class="text-sm">Collapse</span>
			{/if}
		</button>
	</div>
</aside>
