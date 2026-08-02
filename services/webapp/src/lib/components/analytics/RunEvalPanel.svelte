<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		fetchEvalDatasets,
		fetchActiveEvalJob,
		triggerEvalRun,
		cancelActiveEvalJob,
		type EvalDatasetInfo,
		type ActiveEvalJob
	} from '$lib/api/evals';
	import InfoTip from './InfoTip.svelte';

	interface Props {
		/** Called once a run leaves the active state, so the caller can reload the run list. */
		onRunFinished?: () => void;
	}

	let { onRunFinished }: Props = $props();

	const TIERS = [
		{ id: 'generation', label: 'Generation', hint: 'Context injected directly — no ingestion. Fast.' },
		{ id: 'end_to_end', label: 'End to end', hint: 'Ingests documents and runs the full pipeline. Slow.' }
	];

	let datasets = $state<EvalDatasetInfo[]>([]);
	let datasetsError = $state<string | null>(null);

	let name = $state('');
	let tier = $state('generation');
	let selectedDatasets = $state<string[]>(['ragbench']);
	let samples = $state(100);
	let seed = $state<number | null>(42);
	let judgeEnabled = $state(true);

	let activeJob = $state<ActiveEvalJob | null>(null);
	let isSubmitting = $state(false);
	let isCancelling = $state(false);
	let error = $state<string | null>(null);
	let notice = $state<string | null>(null);
	let expanded = $state(false);

	let pollTimer: number | null = null;

	// Only datasets that declare support for the selected tier can be run there.
	let eligibleDatasets = $derived(
		datasets.filter((d) => d.supported_tiers.length === 0 || d.supported_tiers.includes(tier))
	);

	let canSubmit = $derived(
		!isSubmitting && !activeJob && selectedDatasets.length > 0 && samples >= 1
	);

	onMount(async () => {
		try {
			datasets = await fetchEvalDatasets();
		} catch (e) {
			datasetsError = e instanceof Error ? e.message : 'Failed to load datasets';
		}
		await poll();
		pollTimer = window.setInterval(poll, 3000);
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	async function poll() {
		try {
			const next = await fetchActiveEvalJob();
			const finished = activeJob !== null && next === null;
			activeJob = next;
			if (finished) {
				notice = 'Run finished.';
				onRunFinished?.();
			}
		} catch {
			// Transient polling failures are not worth surfacing — the next tick retries.
		}
	}

	function toggleDataset(dsName: string) {
		selectedDatasets = selectedDatasets.includes(dsName)
			? selectedDatasets.filter((d) => d !== dsName)
			: [...selectedDatasets, dsName];
	}

	async function submit() {
		isSubmitting = true;
		error = null;
		notice = null;
		try {
			const job = await triggerEvalRun({
				name: name.trim() || null,
				tier,
				datasets: selectedDatasets,
				samples,
				seed,
				judge_enabled: judgeEnabled
			});
			notice = `Run ${job.job_id} queued.`;
			await poll();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to start run';
		} finally {
			isSubmitting = false;
		}
	}

	async function cancel() {
		isCancelling = true;
		error = null;
		try {
			await cancelActiveEvalJob();
			notice = 'Cancellation requested.';
			await poll();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to cancel run';
		} finally {
			isCancelling = false;
		}
	}

	function fmtElapsed(seconds: number): string {
		const s = Math.round(seconds);
		if (s < 60) return `${s}s`;
		return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
	}

	let progressPct = $derived.by(() => {
		const p = activeJob?.progress;
		if (!p || !p.total_questions) return null;
		return Math.min(100, Math.round((p.current_question / p.total_questions) * 100));
	});
</script>

<div class="term-panel flex flex-col gap-2">
	<div class="flex items-center gap-2 flex-wrap">
		<span class="term-label inline-flex items-center gap-1">
			Run evaluation
			<InfoTip text="Starts an eval run on the evals service. One run at a time; progress and cancellation are live." />
		</span>
		<div class="flex-1 min-w-0"></div>
		{#if !activeJob}
			<button class="btn btn-xs btn-ghost" onclick={() => (expanded = !expanded)}>
				{expanded ? 'Hide options' : 'Options'}
			</button>
			<button class="btn btn-xs btn-primary" onclick={submit} disabled={!canSubmit}>
				{#if isSubmitting}<span class="loading loading-spinner loading-xs"></span>{/if}
				Start run
			</button>
		{/if}
	</div>

	{#if error}
		<div class="alert alert-error text-xs py-1 px-2">
			<span>{error}</span>
			<button class="btn btn-xs btn-ghost" onclick={() => (error = null)}>Dismiss</button>
		</div>
	{/if}
	{#if notice && !activeJob}
		<div class="text-xs text-base-content/60">{notice}</div>
	{/if}

	{#if activeJob}
		{@const p = activeJob.progress}
		<div class="flex flex-col gap-1.5">
			<div class="flex items-center gap-2 text-xs font-mono flex-wrap">
				<span class="loading loading-spinner loading-xs text-warning"></span>
				<span class="badge badge-ghost badge-xs">{activeJob.job_id}</span>
				<span class="capitalize">{activeJob.status}</span>
				<span class="text-base-content/60">{p.phase}</span>
				{#if p.current_dataset}<span class="text-base-content/60">· {p.current_dataset}</span>{/if}
				<span class="text-base-content/60">· {fmtElapsed(p.elapsed_seconds)}</span>
				<div class="flex-1 min-w-0"></div>
				<button class="btn btn-xs btn-error btn-outline" onclick={cancel} disabled={isCancelling}>
					{#if isCancelling}<span class="loading loading-spinner loading-xs"></span>{/if}
					Cancel
				</button>
			</div>
			<div class="flex items-center gap-2">
				{#if progressPct != null}
					<progress class="progress progress-warning flex-1" value={progressPct} max="100"></progress>
					<span class="text-xs font-mono tabular-nums w-28 text-right">
						{p.current_question}/{p.total_questions} ({progressPct}%)
					</span>
				{:else}
					<!-- No question total yet: indeterminate rather than a fabricated number. -->
					<progress class="progress progress-warning flex-1"></progress>
					<span class="text-xs font-mono text-base-content/50 w-28 text-right">starting…</span>
				{/if}
			</div>
		</div>
	{:else if expanded}
		<div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
			<label class="flex flex-col gap-1">
				<span class="term-label">Run name</span>
				<input
					class="input input-xs input-bordered w-full"
					placeholder="auto-generated"
					bind:value={name}
				/>
			</label>

			<label class="flex flex-col gap-1">
				<span class="term-label">Tier</span>
				<select class="select select-xs select-bordered w-full" bind:value={tier}>
					{#each TIERS as t}
						<option value={t.id}>{t.label}</option>
					{/each}
				</select>
				<span class="text-base-content/50">{TIERS.find((t) => t.id === tier)?.hint}</span>
			</label>

			<div class="flex flex-col gap-1 md:col-span-2">
				<span class="term-label">Datasets</span>
				{#if datasetsError}
					<span class="text-error">{datasetsError}</span>
				{:else if datasets.length === 0}
					<span class="text-base-content/50">Loading…</span>
				{:else}
					<div class="flex flex-wrap gap-2">
						{#each eligibleDatasets as ds}
							<label class="flex items-center gap-1.5 cursor-pointer" title={ds.description}>
								<input
									type="checkbox"
									class="checkbox checkbox-xs checkbox-primary"
									checked={selectedDatasets.includes(ds.name)}
									onchange={() => toggleDataset(ds.name)}
								/>
								<span class="font-mono">{ds.name}</span>
							</label>
						{/each}
					</div>
					{#if selectedDatasets.length === 0}
						<span class="text-warning">Select at least one dataset.</span>
					{/if}
				{/if}
			</div>

			<label class="flex flex-col gap-1">
				<span class="term-label">Samples per dataset</span>
				<input
					type="number"
					min="1"
					max="1000"
					class="input input-xs input-bordered w-full"
					bind:value={samples}
				/>
			</label>

			<label class="flex flex-col gap-1">
				<span class="term-label">Seed</span>
				<input
					type="number"
					class="input input-xs input-bordered w-full"
					placeholder="unseeded"
					value={seed ?? ''}
					oninput={(e) => {
						const v = e.currentTarget.value;
						seed = v === '' ? null : Number(v);
					}}
				/>
			</label>

			<label class="flex items-center gap-2 cursor-pointer md:col-span-2">
				<input type="checkbox" class="checkbox checkbox-xs checkbox-primary" bind:checked={judgeEnabled} />
				<span>LLM judge enabled</span>
				<InfoTip text="Disabling the judge skips faithfulness/correctness scoring — faster and cheaper, but the generation group will be empty." />
			</label>
		</div>
	{:else}
		<div class="text-xs text-base-content/50 font-mono">
			{tier} · {selectedDatasets.join(', ') || 'no datasets'} · {samples} samples ·
			judge {judgeEnabled ? 'on' : 'off'}
		</div>
	{/if}
</div>
