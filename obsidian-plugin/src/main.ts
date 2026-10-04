import { homedir } from 'os';
import { FileSystemAdapter, MarkdownView, Notice, Plugin } from 'obsidian';
import { SbError, type StatusInfo } from './contract';
import { checkHealth, type Health } from './health';
import { detectSb } from './locate';
import { RunController } from './run-controller';
import { SbClient } from './sb';
import { DEFAULT_SETTINGS, clampRefresh, loadSettings, saveSettings, type PluginSettings, type Stores } from './settings';
import { statusText } from './status';
import { dailyIndexPath, pickTarget } from './targets';
import { AskModal } from './ui/ask-modal';
import { DoctorModal } from './ui/doctor-modal';
import { QueueModal } from './ui/queue-modal';
import { EsbiSettingTab } from './ui/settings-tab';
import { showProblem } from './ui/problem';

export default class EsbiPlugin extends Plugin {
	settings: PluginSettings = { ...DEFAULT_SETTINGS };
	client!: SbClient;
	runner!: RunController;
	health: Health | null = null;
	status: StatusInfo | null = null;
	private statusEl!: HTMLElement;
	private statusFailed = false;
	private refreshing = false;
	private timer: number | null = null;

	async onload(): Promise<void> {
		this.settings = await loadSettings(this.stores());
		this.client = new SbClient(() => ({ ...this.settings, cwd: this.vaultFolder() }));
		this.runner = new RunController(this.client, () => void this.refreshStatus());
		this.runner.subscribe(() => this.renderStatus());

		this.statusEl = this.addStatusBarItem();
		this.statusEl.addClass('esbi-status', 'mod-clickable');
		this.registerDomEvent(this.statusEl, 'click', () => void this.openQueue(false));
		this.renderStatus();

		this.addRibbonIcon('brain', 'Open the queue', () => void this.openQueue(false));
		this.addCommand({ id: 'add-link', name: "Add the selected link or this note's source to the queue", callback: () => void this.addLink() });
		this.addCommand({ id: 'run-queue', name: 'Run the queue', callback: () => void this.openQueue(true) });
		this.addCommand({ id: 'ask', name: 'Ask your wiki', callback: () => void this.ask() });
		this.addCommand({ id: 'open-today', name: "Open today's index", callback: () => void this.openToday() });
		this.addCommand({ id: 'check-setup', name: 'Check setup', callback: () => void this.checkSetup() });
		this.addSettingTab(new EsbiSettingTab(this.app, this));

		this.restartTimer();
		this.app.workspace.onLayoutReady(() => void this.startup());
	}

	onunload(): void {
		// Stop a running sb the polite way (SIGINT); the timer is cleared by registerInterval.
		this.runner?.cancel();
	}

	/** The vault's folder on disk, which is where sb runs. */
	vaultFolder(): string | undefined {
		const a = this.app.vault.adapter;
		return a instanceof FileSystemAdapter ? a.getBasePath() : undefined;
	}

	private stores(): Stores {
		return {
			loadData: () => this.loadData() as Promise<unknown>,
			saveData: (d) => this.saveData(d),
			loadLocal: (k) => this.app.loadLocalStorage(k) as unknown,
			saveLocal: (k, v) => this.app.saveLocalStorage(k, v),
		};
	}

	async saveSettings(): Promise<void> {
		await saveSettings(this.stores(), this.settings);
		this.health = null; // the path may have changed: check again on next use
		this.restartTimer();
	}

	/** Re-arm the status refresh with the current interval (never below 30 s, see settings). */
	restartTimer(): void {
		if (this.timer !== null) window.clearInterval(this.timer);
		this.settings.statusRefreshSeconds = clampRefresh(this.settings.statusRefreshSeconds);
		this.timer = window.setInterval(() => void this.refreshStatus(), this.settings.statusRefreshSeconds * 1000);
		this.registerInterval(this.timer);
	}

	private async startup(): Promise<void> {
		if (this.settings.sbPath === '') {
			const found = await detectSb(homedir());
			if (found) {
				this.settings.sbPath = found;
				await this.saveSettings();
			}
		}
		if (await this.ensureReady()) await this.refreshStatus();
	}

	/** Checks `sb version --json` (cached). On a problem shows one clear notice and returns false. */
	async ensureReady(): Promise<boolean> {
		this.health ??= await checkHealth(this.client);
		if (this.health.ok) return true;
		showProblem(this.health.error);
		this.renderStatus();
		return false;
	}

	async refreshStatus(): Promise<void> {
		if (this.refreshing || this.runner.active || this.health?.ok !== true) {
			this.renderStatus();
			return;
		}
		this.refreshing = true;
		try {
			this.status = await this.client.status();
			this.statusFailed = false;
		} catch {
			this.statusFailed = true;
		} finally {
			this.refreshing = false;
			this.renderStatus();
		}
	}

	private renderStatus(): void {
		const text = statusText({
			ready: this.health?.ok === true,
			status: this.status,
			run: this.runner.state,
			running: this.runner.active,
			failedToRead: this.statusFailed,
		});
		this.statusEl.setText(text);
		this.statusEl.setAttr('aria-label', 'esbi-cli queue: click to open');
	}

	async openQueue(startRun: boolean): Promise<void> {
		if (!(await this.ensureReady())) return;
		new QueueModal(this.app, this, startRun).open();
	}

	private async addLink(): Promise<void> {
		const view = this.app.workspace.getActiveViewOfType(MarkdownView);
		const file = view?.file ?? this.app.workspace.getActiveFile();
		const source: unknown = file ? this.app.metadataCache.getFileCache(file)?.frontmatter?.source : undefined;
		const target = pickTarget({ selection: view?.editor.getSelection() ?? '', source });
		if ('problem' in target) {
			new Notice(target.problem);
			return;
		}
		if (!(await this.ensureReady())) return;
		try {
			const r = await this.client.add(target.url);
			new Notice(r.queued > 0 ? `Queued: ${target.url}` : 'Already in the queue or in your wiki.');
		} catch (e) {
			new Notice(`Could not queue the link: ${e instanceof SbError ? e.message : String(e)}`);
		}
		void this.refreshStatus();
	}

	private async ask(): Promise<void> {
		if (await this.ensureReady()) new AskModal(this.app, this).open();
	}

	private async checkSetup(): Promise<void> {
		if (await this.ensureReady()) new DoctorModal(this.app, this).open();
	}

	private async openToday(): Promise<void> {
		const path = dailyIndexPath(new Date());
		const file = this.app.vault.getFileByPath(path);
		if (!file) {
			new Notice(`There is no index for today yet (${path}). Run the queue to create it.`);
			return;
		}
		await this.app.workspace.getLeaf(false).openFile(file);
	}
}
