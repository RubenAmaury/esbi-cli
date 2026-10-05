// The queue window's Run button and the Ask window's submit must go through the plugin's guard, never straight to
// sb. The real windows run over a tiny fake of Obsidian's Modal; the plugin is a stub that records what it was asked.
import { describe, expect, it, vi } from 'vitest';
import { FakeModal, buttonIn } from './fake-dom';

vi.mock('obsidian', async () => {
	const { FakeModal: Modal } = await import('./fake-dom');
	class Component {
		load() {}
		unload() {}
	}
	return { Modal, Component, MarkdownRenderer: { render: () => Promise.resolve() } };
});

const { QueueModal } = await import('../src/ui/queue-modal');
const { AskModal } = await import('../src/ui/ask-modal');

const root = () => (FakeModal.last as FakeModal).contentEl;

describe('the queue window', () => {
	it('its Run button asks the plugin to start the run (which guards it), and never starts one itself', () => {
		const plugin = {
			runner: { state: null, active: false, subscribe: () => () => undefined, start: vi.fn() },
			status: null,
			refreshStatus: () => Promise.resolve(),
			startRun: vi.fn(() => Promise.resolve(false)),
		};
		new QueueModal({} as never, plugin as never, false).open();
		buttonIn(root(), /Run the queue/).handlers.click?.();
		expect(plugin.startRun).toHaveBeenCalledTimes(1);
		expect(plugin.runner.start).not.toHaveBeenCalled();
	});
});

describe('the Ask window', () => {
	const setup = (answer: unknown) => {
		const plugin = { askWiki: vi.fn(() => Promise.resolve(answer)), client: { ask: vi.fn() } };
		new AskModal({} as never, plugin as never).open();
		const input = root().children.find((e) => e.tag === 'textarea');
		if (input) input.value = 'what is a harness?';
		return plugin;
	};

	it('sends the question through the plugin, which guards it, and never to sb directly', async () => {
		const plugin = setup(null);
		buttonIn(root(), /Ask/).handlers.click?.();
		await vi.waitFor(() => expect(plugin.askWiki).toHaveBeenCalledWith('what is a harness?', expect.anything()));
		expect(plugin.client.ask).not.toHaveBeenCalled();
	});

	it('shows nothing, and can be used again, when the guard blocked the question', async () => {
		setup(null);
		const ask = buttonIn(root(), /Ask/);
		ask.handlers.click?.();
		await vi.waitFor(() => expect(ask.disabled).toBe(false));
		expect(root().children.find((e) => e.cls === 'esbi-answer')?.children).toEqual([]);
	});
});
