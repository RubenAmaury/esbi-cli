import { Notice } from 'obsidian';
import type { SbError } from '../contract';
import { explain } from '../health';

/** One notice with what is wrong and what to do. The plugin never runs the commands: the user does. */
export function showProblem(error: SbError): void {
	const x = explain(error);
	const frag = createFragment((f) => {
		f.createEl('strong', { text: `esbi-cli: ${x.title}` });
		for (const step of x.steps) f.createDiv({ text: step });
		for (const cmd of x.commands) f.createEl('code', { text: cmd, cls: 'esbi-command' });
	});
	new Notice(frag, 20_000);
}

/** A code line with a Copy button. */
export function commandRow(parent: HTMLElement, command: string): void {
	const row = parent.createDiv({ cls: 'esbi-command-row' });
	row.createEl('code', { text: command });
	const btn = row.createEl('button', { text: 'Copy' });
	btn.addEventListener('click', () => {
		void navigator.clipboard.writeText(command).then(() => new Notice('Copied.'));
	});
}
