// The real confirmation window logic over a tiny fake of Obsidian's Modal: Cancel is the default, only a click on
// the other button says yes, and closing the window any other way (Escape, the x) says no.
import { describe, expect, it, vi } from 'vitest';
import { FakeModal, allEls, buttonIn, type FakeEl } from './fake-dom';

vi.mock('obsidian', async () => ({ Modal: (await import('./fake-dom')).FakeModal }));

const { confirmCloud } = await import('../src/ui/confirm-modal');

const root = () => (FakeModal.last as FakeModal).contentEl;
const open = () => confirmCloud({} as never, { title: 'Send text to a cloud model?', lines: ['summarize: anthropic/x', 'Nothing else leaves.'] });

describe('confirmCloud', () => {
	it('shows the title and every line, and focuses Cancel, not the button that says yes', () => {
		void open();
		expect(FakeModal.last?.title).toBe('Send text to a cloud model?');
		expect(allEls(root()).map((e: FakeEl) => e.text)).toContain('summarize: anthropic/x');
		expect(buttonIn(root(), /Cancel/).focused).toBe(true);
		expect(buttonIn(root(), /Send/).focused).toBe(false);
	});

	it('Cancel says no', async () => {
		const answer = open();
		buttonIn(root(), /Cancel/).handlers.click?.();
		expect(await answer).toBe(false);
	});

	it('the other button says yes', async () => {
		const answer = open();
		buttonIn(root(), /Send/).handlers.click?.();
		expect(await answer).toBe(true);
	});

	it('closing the window without a choice (Escape, the x) says no', async () => {
		const answer = open();
		(FakeModal.last as FakeModal).close();
		expect(await answer).toBe(false);
	});
});
