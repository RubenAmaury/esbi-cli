// A tiny fake of the DOM calls Obsidian's Modal windows make, enough to click their buttons in a Node test.
export interface FakeEl {
	tag: string;
	text: string;
	cls: string;
	value: string;
	focused: boolean;
	disabled: boolean;
	handlers: Record<string, (e?: unknown) => void>;
	children: FakeEl[];
	createEl(tag: string, o?: { text?: string; cls?: string }): FakeEl;
	createDiv(o?: { text?: string; cls?: string }): FakeEl;
	addEventListener(type: string, fn: (e?: unknown) => void): void;
	focus(): void;
	empty(): void;
	setText(t: string): void;
}

export const fakeEl = (tag = 'div', o: { text?: string; cls?: string } = {}): FakeEl => {
	const el: FakeEl = {
		tag,
		text: o.text ?? '',
		cls: o.cls ?? '',
		value: '',
		focused: false,
		disabled: false,
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
		setText: (t) => {
			el.text = t;
		},
	};
	return el;
};

export const allEls = (el: FakeEl): FakeEl[] => [el, ...el.children.flatMap(allEls)];

/** Obsidian's Modal: `open()` runs `onOpen()`, `close()` runs `onClose()`. */
export class FakeModal {
	static last: FakeModal | null = null;
	contentEl = fakeEl();
	title = '';
	constructor(public app: unknown) {
		FakeModal.last = this;
	}
	setTitle(t: string): void {
		this.title = t;
	}
	open(): void {
		(this as unknown as { onOpen(): void }).onOpen();
	}
	close(): void {
		(this as unknown as { onClose(): void }).onClose();
	}
}

export const buttonIn = (root: FakeEl, text: RegExp): FakeEl => {
	const b = allEls(root).find((e) => e.tag === 'button' && text.test(e.text));
	if (!b) throw new Error(`no button ${text}`);
	return b;
};
