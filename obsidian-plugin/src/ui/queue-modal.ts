import { Modal, type App } from 'obsidian';
import { runMessage, type RunState } from '../run-state';
import type EsbiPlugin from '../main';

/** The queue: counts when idle, live progress while `sb run --json` works, the result after. */
export class QueueModal extends Modal {
	private off: (() => void) | null = null;

	constructor(
		app: App,
		private readonly plugin: EsbiPlugin,
		private readonly startRun: boolean,
	) {
		super(app);
	}

	onOpen(): void {
		this.setTitle('Source queue');
		this.off = this.plugin.runner.subscribe(() => this.render());
		if (this.startRun) this.plugin.runner.start();
		this.render();
		if (!this.plugin.runner.active) void this.plugin.refreshStatus().then(() => this.render());
	}

	onClose(): void {
		this.off?.(); // closing the window does not stop the run: the status bar keeps showing it
		this.contentEl.empty();
	}

	private render(): void {
		const { contentEl } = this;
		contentEl.empty();
		const runner = this.plugin.runner;
		const s = runner.state;
		if (runner.active && s) this.renderProgress(s);
		else if (s) this.renderResult(s);
		else this.renderIdle();
	}

	private renderIdle(): void {
		const { contentEl } = this;
		const q = this.plugin.status?.queue;
		contentEl.createEl('p', {
			text: q ? `${q.queued} queued, ${q.processing} in progress, ${q.done} done, ${q.failed} failed.` : 'Reading the queue...',
		});
		for (const f of this.plugin.status?.failed ?? []) {
			contentEl.createDiv({ cls: 'esbi-failed', text: `${f.target}: ${f.error}` });
		}
		this.runButton('Run the queue');
	}

	private renderProgress(s: RunState): void {
		const { contentEl } = this;
		const finished = s.done.length + s.failed.length;
		contentEl.createEl('p', { text: s.queued > 0 ? `Source ${Math.min(finished + 1, s.queued)} of ${s.queued}` : 'Starting...' });
		if (s.queued > 0) contentEl.createEl('progress', { attr: { max: String(s.queued), value: String(finished) }, cls: 'esbi-progress' });
		if (s.current) {
			contentEl.createDiv({ cls: 'esbi-current', text: s.current.title });
			const step = s.current.step;
			if (step) contentEl.createDiv({ cls: 'esbi-step', text: `${step.name} ${step.index}/${step.total}` });
		}
		this.renderItems(s);
		const cancel = contentEl.createEl('button', { text: 'Cancel', cls: 'mod-warning' });
		cancel.addEventListener('click', () => {
			cancel.disabled = true;
			cancel.setText('Cancelling...');
			this.plugin.runner.cancel();
		});
	}

	private renderResult(s: RunState): void {
		const { contentEl } = this;
		contentEl.createEl('p', { text: runMessage(s), cls: s.phase === 'failed' ? 'esbi-error' : '' });
		this.renderItems(s);
		this.runButton('Run again');
	}

	private renderItems(s: RunState): void {
		const list = this.contentEl.createEl('ul', { cls: 'esbi-items' });
		for (const d of s.done) list.createEl('li', { text: `Added: ${d.title}`, cls: 'esbi-done' });
		for (const f of s.failed) {
			const why = f.reason ? ` (${f.reason})` : '';
			list.createEl('li', { text: `${f.parked ? 'Gave up on' : 'Failed'}: ${f.title}${why}`, cls: 'esbi-failed' });
		}
	}

	private runButton(label: string): void {
		const btn = this.contentEl.createEl('button', { text: label, cls: 'mod-cta' });
		btn.addEventListener('click', () => void this.plugin.startRun());
	}
}
