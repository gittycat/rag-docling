<script lang="ts">
	import { showTooltips } from '$lib/stores/ui';
</script>

<div class="container mx-auto p-6 max-w-4xl">
	<h1 class="text-2xl font-bold mb-6">Settings</h1>

	<!-- User Interface Section -->
	<div class="card bg-base-200 shadow-sm mb-4">
		<div class="card-body">
			<h2 class="card-title text-lg">User Interface</h2>
			<div class="form-control">
				<label class="label cursor-pointer justify-start gap-3">
					<input
						type="checkbox"
						class="checkbox checkbox-sm"
						bind:checked={$showTooltips}
					/>
					<span class="label-text">Show help tooltips</span>
				</label>
			</div>
		</div>
	</div>
</div>
