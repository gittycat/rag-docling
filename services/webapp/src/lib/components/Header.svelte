<script lang="ts">
	import { page } from '$app/stores';
</script>

<header class="bg-gray-800 text-white shadow-lg">
	<nav class="container mx-auto px-4 py-4">
		<div class="flex items-center justify-between">
			<h1 class="text-2xl font-bold">RAG System</h1>
			<div class="flex gap-6">
				<a
					href="/"
					class="px-4 py-2 rounded transition"
					class:bg-gray-700={$page.url.pathname === '/'}
					class:bg-transparent={$page.url.pathname !== '/'}
					class:hover:bg-gray-700={$page.url.pathname !== '/'}
				>
					Home
				</a>
				<a
					href="/admin"
					class="px-4 py-2 rounded transition"
					class:bg-gray-700={$page.url.pathname === '/admin'}
					class:bg-transparent={$page.url.pathname !== '/admin'}
					class:hover:bg-gray-700={$page.url.pathname !== '/admin'}
				>
					Admin
				</a>
				<a
					href="/about"
					class="px-4 py-2 rounded transition"
					class:bg-gray-700={$page.url.pathname === '/about'}
					class:bg-transparent={$page.url.pathname !== '/about'}
					class:hover:bg-gray-700={$page.url.pathname !== '/about'}
				>
					About
				</a>
			</div>
		</div>
	</nav>
</header>
