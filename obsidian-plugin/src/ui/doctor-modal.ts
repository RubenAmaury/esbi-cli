import { Modal, type App } from 'obsidian';
import { SbError } from '../contract';
import { explain } from '../health';
import type EsbiPlugin from '../main';
import { commandRow } from './problem';

/** `sb doctor --json` as a list: what is fine, what is not, and the fix for each. */
export class DoctorModal extends Modal {
	constructor(
		app: App,
		private readonly plugin: EsbiPlugin,
	) {
		super(app);
	}

	onOpen(): void {
		this.setTitle('Setup check');
		void this.check();
	}

	onClose(): void {
		this.contentEl.empty();
	}

	private async check(): Promise<void> {
		const { contentEl } = this;
		contentEl.empty();
		contentEl.createEl('p', { text: 'Checking...' });
		try {
			const d = await this.plugin.client.doctor();
			contentEl.empty();
			contentEl.createEl('p', { text: d.ok ? 'Everything looks fine.' : 'Some checks need attention.', cls: d.ok ? '' : 'esbi-error' });
			const list = contentEl.createEl('ul', { cls: 'esbi-checks' });
			for (const c of d.checks) {
				const li = list.createEl('li', { cls: `esbi-check esbi-level-${c.level.toLowerCase()}` });
				li.createSpan({ text: c.level, cls: 'esbi-badge' });
				li.createSpan({ text: ` ${c.text}` });
				if (c.fix) li.createDiv({ text: `Fix: ${c.fix}`, cls: 'esbi-fix' });
			}
		} catch (e) {
			contentEl.empty();
			const x = e instanceof SbError ? explain(e) : { title: String(e), steps: [], commands: [] };
			contentEl.createEl('p', { text: x.title, cls: 'esbi-error' });
			x.steps.forEach((step) => contentEl.createEl('p', { text: step }));
			x.commands.forEach((cmd) => commandRow(contentEl, cmd));
		}
		const again = contentEl.createEl('button', { text: 'Check again' });
		again.addEventListener('click', () => void this.check());
	}
}
