import { Component, MarkdownRenderer, Modal, type App } from 'obsidian';
import { stripRemoteContent } from '../answer';
import { SbError, type AskInfo } from '../contract';
import type EsbiPlugin from '../main';

/** Ask a question, get the answer from your wiki with the pages it cites as links. */
export class AskModal extends Modal {
	private abort: AbortController | null = null;
	private resultEl!: HTMLElement;
	/** Owns the rendered Markdown: unloaded when the window closes. */
	private readonly renderer = new Component();

	constructor(
		app: App,
		private readonly plugin: EsbiPlugin,
	) {
		super(app);
	}

	onOpen(): void {
		this.setTitle('Ask your wiki');
		this.renderer.load();
		const input = this.contentEl.createEl('textarea', { cls: 'esbi-question', attr: { rows: '3', placeholder: 'What is an agent harness?' } });
		const button = this.contentEl.createEl('button', { text: 'Ask', cls: 'mod-cta' });
		this.resultEl = this.contentEl.createDiv({ cls: 'esbi-answer' });
		const submit = (): void => void this.submit(input.value, button);
		button.addEventListener('click', submit);
		input.addEventListener('keydown', (e) => {
			if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit();
		});
		input.focus();
	}

	onClose(): void {
		this.abort?.abort(); // closing the window cancels the question
		this.renderer.unload();
		this.contentEl.empty();
	}

	private async submit(question: string, button: HTMLButtonElement): Promise<void> {
		const q = question.trim();
		if (q === '' || this.abort) return;
		this.abort = new AbortController();
		const signal = this.abort.signal;
		button.disabled = true;
		this.resultEl.empty();
		this.resultEl.createEl('p', { text: 'Thinking. This can take a minute with a local model.' });
		try {
			const a = await this.plugin.client.ask(q, signal);
			if (!signal.aborted) await this.show(a);
		} catch (e) {
			if (!signal.aborted) {
				this.resultEl.empty();
				this.resultEl.createEl('p', { text: e instanceof SbError ? e.message : String(e), cls: 'esbi-error' });
			}
		} finally {
			this.abort = null;
			button.disabled = false;
		}
	}

	private async show(a: AskInfo): Promise<void> {
		const el = this.resultEl;
		el.empty();
		if (a.refused) el.createEl('p', { text: 'Your wiki does not have enough to answer this.', cls: 'esbi-error' });
		const body = el.createDiv({ cls: 'esbi-answer-body' });
		// The answer is Markdown with [[links]]; Obsidian renders it. Images are removed first: see stripRemoteContent.
		await MarkdownRenderer.render(this.app, stripRemoteContent(a.answer), body, '', this.renderer);
		body.findAll('a.internal-link').forEach((link) => this.wireLink(link));
		if (a.cited.length > 0) {
			el.createEl('h4', { text: 'Pages used' });
			const list = el.createEl('ul', { cls: 'esbi-cited' });
			for (const title of a.cited) {
				const li = list.createEl('li');
				if (this.exists(title)) this.wireLink(li.createEl('a', { text: title, cls: 'internal-link', attr: { 'data-href': title, href: title } }));
				else li.setText(`${title} (not found in this vault)`);
			}
		}
	}

	private exists(linkText: string): boolean {
		return this.app.metadataCache.getFirstLinkpathDest(linkText.split('#')[0] ?? '', '') !== null;
	}

	/** Open a page that exists; never create one from a link the model wrote. */
	private wireLink(a: HTMLElement): void {
		const href = a.getAttr('data-href') ?? a.getAttr('href') ?? '';
		if (!this.exists(href)) {
			a.replaceWith(createSpan({ text: a.getText() }));
			return;
		}
		a.addEventListener('click', (evt) => {
			evt.preventDefault();
			void this.app.workspace.openLinkText(href, '', evt.ctrlKey || evt.metaKey);
			this.close();
		});
	}
}
