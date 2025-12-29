<script lang="ts">
	import { showTooltips } from '$lib/stores/ui';
</script>

<div class="flex flex-col gap-2">
	<!-- User Interface Section -->
	<div class="bg-base-200 rounded p-2">
		<div class="text-xs font-semibold mb-1 text-base-content/70">User Interface</div>
		<label class="flex items-center gap-2 text-xs cursor-pointer">
			<input
				type="checkbox"
				class="checkbox checkbox-xs rounded-none"
				bind:checked={$showTooltips}
			/>
			<span>Show help tooltips</span>
		</label>
	</div>
</div>
