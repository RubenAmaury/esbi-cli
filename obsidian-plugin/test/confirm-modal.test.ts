// The real confirmation window logic over a tiny fake of Obsidian's Modal: Cancel is the default, only a click on
// the other button says yes, and closing the window any other way (Escape, the x) says no.
import { describe, expect, it, vi } from 'vitest';

interface FakeEl {
	tag: string;
	text: string;
	cls: string;
	focused: boolean;
	handlers: Record<string, () => void>;
	children: FakeEl[];
	createEl(tag: string, o?: { text?: string; cls?: string }): FakeEl;
	createDiv(o?: { text?: string; cls?: string }): FakeEl;
	addEventListener(type: string, fn: () => void): void;
	focus(): void;
	empty(): void;
}

const fakeEl = (tag = 'div', o: { text?: string; cls?: string } = {}): FakeEl => {
	const el: FakeEl = {
		tag,
		text: o.text ?? '',
		cls: o.cls ?? '',
		focused: false,
		handlers: {},
		children: [],
		createEl: (t, opts) => {
			const c = fakeEl(t, opts);
			el.children.push(c);
			return c;
		},
		createDiv: (opts) => el.createEl('div', opts),
		addEventListener: (type, fn) => {
			el.handlers[type] = fn;
		},
		focus: () => {
			el.focused = true;
		},
		empty: () => {
			el.children = [];
		},
	};
	return el;
};

let last: { contentEl: FakeEl; title: string } | null = null;

vi.mock('obsidian', () => ({
	Modal: class {
		contentEl = fakeEl();
		title = '';
		constructor(public app: unknown) {
			last = this as unknown as { contentEl: FakeEl; title: string };
		}
		setTitle(t: string) {
			this.title = t;
		}
		open() {
			(this as unknown as { onOpen(): void }).onOpen();
		}
		close() {
			(this as unknown as { onClose(): void }).onClose();
		}
	},
}));

const { confirmCloud } = await import('../src/ui/confirm-modal');

const all = (el: FakeEl): FakeEl[] => [el, ...el.children.flatMap(all)];
const button = (text: RegExp) => {
	const b = all(last?.contentEl as FakeEl).find((e) => e.tag === 'button' && text.test(e.text));
	if (!b) throw new Error(`no button ${text}`);
	return b;
};
const open = () => confirmCloud({} as never, { title: 'Send text to a cloud model?', lines: ['summarize: anthropic/x', 'Nothing else leaves.'] });

describe('confirmCloud', () => {
	it('shows the title and every line, and focuses Cancel, not the button that says yes', () => {
		void open();
		expect(last?.title).toBe('Send text to a cloud model?');
		const texts = all(last?.contentEl as FakeEl).map((e) => e.text);
		expect(texts).toContain('summarize: anthropic/x');
		expect(button(/Cancel/).focused).toBe(true);
		expect(button(/Send/).focused).toBe(false);
	});

	it('Cancel says no', async () => {
		const answer = open();
		button(/Cancel/).handlers.click?.();
		expect(await answer).toBe(false);
	});

	it('the other button says yes', async () => {
		const answer = open();
		button(/Send/).handlers.click?.();
		expect(await answer).toBe(true);
	});

	it('closing the window without a choice (Escape, the x) says no', async () => {
		const answer = open();
		(last as unknown as { close(): void }).close();
		expect(await answer).toBe(false);
	});
});
