// Wiring test: the real src/main.ts with Obsidian replaced by small fakes and the real fake-sb behind it.
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { FAKE_SB, ensureFakeSbExecutable, readArgv, scratchDir } from './helpers';

const notices: string[] = [];
const modals: { name: string; startRun?: boolean }[] = [];

vi.mock('obsidian', () => {
	class FileSystemAdapter {
		constructor(private readonly base: string) {}
		getBasePath(): string {
			return this.base;
		}
	}
	class Plugin {
		commands: { id: string; name: string; callback: () => void }[] = [];
		ribbon: string[] = [];
		intervals: number[] = [];
		stored: unknown = null;
		statusEl = { text: '', classes: [] as string[], listeners: {} as Record<string, () => void>, addClass(...c: string[]) { this.classes.push(...c); }, setText(t: string) { this.text = t; }, setAttr() {} };
		constructor(public app: unknown) {}
		addCommand(c: { id: string; name: string; callback: () => void }) { this.commands.push(c); }
		addRibbonIcon(icon: string) { this.ribbon.push(icon); return {}; }
		addStatusBarItem() { return this.statusEl; }
		addSettingTab() {}
		registerInterval(id: number) { this.intervals.push(id); return id; }
		registerDomEvent(el: { listeners: Record<string, () => void> }, type: string, cb: () => void) { el.listeners[type] = cb; }
		loadData() { return Promise.resolve(this.stored); }
		saveData(d: unknown) { this.stored = d; return Promise.resolve(); }
	}
	class Notice { constructor(m: unknown) { notices.push(typeof m === 'string' ? m : 'fragment'); } }
	class Modal {}
	class PluginSettingTab {}
	class Setting {}
	class Component {}
	class MarkdownView {}
	const MarkdownRenderer = {};
	return { FileSystemAdapter, Plugin, Notice, Modal, PluginSettingTab, Setting, Component, MarkdownView, MarkdownRenderer };
});
vi.mock('../src/ui/queue-modal', () => ({ QueueModal: class { constructor(_a: unknown, _p: unknown, startRun: boolean) { modals.push({ name: 'queue', startRun }); } open() {} } }));
vi.mock('../src/ui/ask-modal', () => ({ AskModal: class { constructor() { modals.push({ name: 'ask' }); } open() {} } }));
vi.mock('../src/ui/doctor-modal', () => ({ DoctorModal: class { constructor() { modals.push({ name: 'doctor' }); } open() {} } }));
vi.mock('../src/ui/problem', () => ({ showProblem: (e: { kind: string }) => notices.push(`problem:${e.kind}`), commandRow: () => undefined }));
vi.mock('../src/ui/settings-tab', () => ({ EsbiSettingTab: class {} }));

const { FileSystemAdapter, MarkdownView } = await import('obsidian');
const { default: EsbiPlugin } = await import('../src/main');

beforeAll(ensureFakeSbExecutable);
beforeEach(() => {
	notices.length = 0;
	modals.length = 0;
});
afterEach(() => vi.unstubAllEnvs());

interface Setup {
	selection?: string;
	source?: unknown;
	sbPath?: string;
}

async function load(o: Setup = {}) {
	const local = new Map<string, unknown>([['esbi-sb-path', o.sbPath ?? FAKE_SB]]);
	const view = Object.assign(new MarkdownView(), { editor: { getSelection: () => o.selection ?? '' }, file: { path: 'n.md' } });
	const app = {
		loadLocalStorage: (k: string) => local.get(k) ?? null,
		saveLocalStorage: (k: string, v: unknown) => void local.set(k, v),
		vault: { adapter: new (FileSystemAdapter as unknown as new (b: string) => object)(scratchDir()), getFileByPath: () => null },
		workspace: {
			onLayoutReady: (cb: () => void) => cb(),
			getActiveViewOfType: () => view,
			getActiveFile: () => view.file,
			getLeaf: () => ({ openFile: vi.fn() }),
		},
		metadataCache: { getFileCache: () => ({ frontmatter: { source: o.source } }) },
	};
	const plugin = new (EsbiPlugin as unknown as new (a: unknown) => InstanceType<typeof EsbiPlugin> & { commands: { id: string; name: string; callback: () => void }[]; ribbon: string[]; intervals: number[]; statusEl: { text: string; classes: string[]; listeners: Record<string, () => void> }; stored: unknown })(app);
	await plugin.onload();
	return plugin;
}
const run = (p: Awaited<ReturnType<typeof load>>, id: string) => p.commands.find((c) => c.id === id)?.callback();

describe('plugin wiring', () => {
	it('registers the five commands, a ribbon icon and a clickable status bar item', async () => {
		const p = await load();
		expect(p.commands.map((c) => c.id)).toEqual(['add-link', 'run-queue', 'ask', 'open-today', 'check-setup']);
		for (const c of p.commands) {
			expect(c.id).not.toMatch(/esbi|obsidian/); // Obsidian prefixes the plugin id itself
			expect(c.name).not.toMatch(/obsidian/i);
		}
		expect(p.ribbon).toEqual(['brain']);
		expect(p.statusEl.classes).toContain('mod-clickable');
		p.onunload();
	});

	it('checks the contract on load and shows the queue in the status bar', async () => {
		const p = await load();
		await vi.waitFor(() => expect(p.statusEl.text).toBe('esbi: 3 queued, 1 failed'));
		expect(notices).toEqual([]);
		p.onunload();
	});

	it('shows one clear notice, and no crash, when the contract is newer than the plugin', async () => {
		vi.stubEnv('FAKE_SB_CONTRACT', '2');
		const p = await load();
		await vi.waitFor(() => expect(notices).toEqual(['problem:too_new']));
		expect(p.statusEl.text).toBe('esbi: not set up');
		run(p, 'ask'); // commands refuse politely too
		await vi.waitFor(() => expect(notices.length).toBe(2));
		expect(modals).toEqual([]);
		p.onunload();
	});

	it('shows a notice when sb is missing', async () => {
		const p = await load({ sbPath: '/nonexistent/dir/sb' });
		await vi.waitFor(() => expect(notices).toEqual(['problem:missing']));
		expect(p.statusEl.text).toBe('esbi: not set up');
		p.onunload();
	});

	it('never polls faster than every 30 seconds, even if data.json says 1', async () => {
		const spy = vi.spyOn(globalThis, 'setInterval');
		const p = await load();
		// the plugin starts from stored data: simulate a hand-edited file by saving through its own path
		p.settings.statusRefreshSeconds = 1;
		await p.saveSettings();
		expect(p.stored).toEqual({ statusRefreshSeconds: 30 });
		const delays = spy.mock.calls.map((c) => c[1]);
		expect(delays.length).toBeGreaterThan(0);
		expect(Math.min(...(delays as number[]))).toBeGreaterThanOrEqual(30_000);
		spy.mockRestore();
		p.onunload();
	});

	it('queues the selected link with sb add, putting the URL after --', async () => {
		const argvFile = join(scratchDir(), 'argv');
		vi.stubEnv('FAKE_SB_ARGV_FILE', argvFile);
		const p = await load({ selection: '[a "title"; $(rm -rf ~)](https://example.com/page)' });
		run(p, 'add-link');
		await vi.waitFor(() => expect(notices).toContain('Queued: https://example.com/page'));
		expect(readArgv(`${argvFile}.add`)).toEqual(['add', '--json', '--', 'https://example.com/page']);
		p.onunload();
	});

	it('refuses a selection that is not a web link without starting any process', async () => {
		const argvFile = join(scratchDir(), 'argv');
		vi.stubEnv('FAKE_SB_ARGV_FILE', argvFile);
		const p = await load({ selection: 'rm -rf ~; https://x' });
		await vi.waitFor(() => expect(p.statusEl.text).toBe('esbi: 3 queued, 1 failed'));
		run(p, 'add-link');
		await vi.waitFor(() => expect(notices.length).toBe(1));
		expect(notices[0]).toMatch(/not a single web link/);
		expect(existsSync(`${argvFile}.add`)).toBe(false); // sb add was never started
		p.onunload();
	});

	it('refuses an email note: its source is not a web link', async () => {
		const p = await load({ source: 'mail:<abc@mail.gmail.com>' });
		run(p, 'add-link');
		await vi.waitFor(() => expect(notices.length).toBe(1));
		expect(notices[0]).toMatch(/not a web link/);
		p.onunload();
	});

	it('opens the queue window from the command, the ribbon path and the status bar click', async () => {
		const p = await load();
		await vi.waitFor(() => expect(p.statusEl.text).toBe('esbi: 3 queued, 1 failed'));
		run(p, 'run-queue');
		await vi.waitFor(() => expect(modals).toEqual([{ name: 'queue', startRun: true }]));
		p.statusEl.listeners.click?.();
		await vi.waitFor(() => expect(modals.at(-1)).toEqual({ name: 'queue', startRun: false }));
		p.onunload();
	});

	it('cancels a running sb when the plugin unloads', async () => {
		vi.stubEnv('FAKE_SB_STEP_SECONDS', '0.3');
		vi.stubEnv('FAKE_SB_SOURCES', '5');
		const p = await load();
		p.runner.start();
		await vi.waitFor(() => expect(p.runner.state?.current).not.toBeNull());
		p.onunload();
		await vi.waitFor(() => expect(p.runner.active).toBe(false), { timeout: 10_000 });
		expect(p.runner.state?.canceled).toBe(true);
	});
});
