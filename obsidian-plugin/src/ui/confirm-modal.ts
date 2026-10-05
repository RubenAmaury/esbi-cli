import { Modal, type App } from 'obsidian';

class ConfirmModal extends Modal {
	private yes = false;

	constructor(
		app: App,
		private readonly text: { title: string; lines: string[] },
		private readonly done: (yes: boolean) => void,
	) {
		super(app);
	}

	onOpen(): void {
		this.setTitle(this.text.title);
		for (const line of this.text.lines) this.contentEl.createEl('p', { text: line });
		const row = this.contentEl.createDiv({ cls: 'modal-button-container' });
		const cancel = row.createEl('button', { text: 'Cancel', cls: 'mod-cta' });
		const go = row.createEl('button', { text: 'Send to the cloud model', cls: 'mod-warning' });
		cancel.addEventListener('click', () => this.close());
		go.addEventListener('click', () => {
			this.yes = true;
			this.close();
		});
		cancel.focus(); // Enter chooses Cancel
	}

	onClose(): void {
		this.contentEl.empty();
		this.done(this.yes); // Escape or the x is a no
	}
}

/** A yes only when the person clicks the send button; Cancel is focused, and any other way out is a no. */
export const confirmCloud = (app: App, text: { title: string; lines: string[] }): Promise<boolean> =>
	new Promise((resolve) => new ConfirmModal(app, text, resolve).open());
