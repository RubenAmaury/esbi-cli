import { homedir } from 'os';
import { FileSystemAdapter, MarkdownView, Notice, Plugin } from 'obsidian';
import { SbError, type AskInfo, type InfoInfo, type StatusInfo } from './contract';
import { cloudConfirmation, cloudKey, cloudModels, sameFolder, vaultProblem, type CloudScope } from './guards';
import { checkHealth, type Health } from './health';
import { detectSb } from './locate';
import { RunController } from './run-controller';
import { SbClient } from './sb';
import { DEFAULT_SETTINGS, clampRefresh, loadSettings, saveSettings, type PluginSettings, type Stores } from './settings';
import { statusText } from './status';
import { dailyIndexPath, pickTarget } from './targets';
import { AskModal } from './ui/ask-modal';
import { confirmCloud } from './ui/confirm-modal';
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
	private otherVault = false;
	/** Cloud-model questions the person said yes to. Memory only, never saved: a new session asks again. */
	private readonly cloudAcked = new Set<string>();
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
			const mine = this.vaultFolder();
			this.otherVault = mine !== undefined && this.status.vault !== '' && !sameFolder(mine, this.status.vault);
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
			otherVault: this.otherVault,
		});
		this.statusEl.setText(text);
		this.statusEl.setAttr('aria-label', 'esbi-cli queue: click to open');
	}

	/**
	 * The one gate for everything that writes to the wiki or sends text anywhere: Add, Run, Ask. Returns false, after
	 * saying why in one notice, unless sb uses the vault that is open and (Run, Ask) any cloud model was confirmed.
	 * Add sends no text to a model, so it only needs the vault check.
	 */
	async guard(scope: 'add' | CloudScope): Promise<boolean> {
		if (!(await this.ensureReady())) return false;
		let info: InfoInfo;
		try {
			info = await this.client.info(); // fresh every time: the config may have changed since the last command
		} catch (e) {
			new Notice(`Could not check which vault esbi-cli uses: ${e instanceof SbError ? e.message : String(e)} Nothing was done.`, 15000);
			return false;
		}
		const problem = vaultProblem(this.vaultFolder(), info);
		if (problem) {
			new Notice(`${problem} Nothing was done.`, 15000);
			void this.refreshStatus();
			return false;
		}
		if (scope === 'add') return true;
		const cloud = cloudModels(info.models, scope);
		if (cloud.length === 0) return true;
		const key = cloudKey(scope, cloud);
		if (this.cloudAcked.has(key)) return true;
		if (!(await confirmCloud(this.app, cloudConfirmation(scope, cloud)))) return false;
		this.cloudAcked.add(key);
		return true;
	}

	/** Start `sb run` if the guard allows it; the queue window's buttons come here too. False when nothing started. */
	async startRun(): Promise<boolean> {
		if (this.runner.active || !(await this.guard('run'))) return false;
		return this.runner.start();
	}

	/** Send a question to `sb ask` if the guard allows it; null when it was blocked (the person was told why). */
	async askWiki(question: string, signal?: AbortSignal): Promise<AskInfo | null> {
		if (!(await this.guard('ask'))) return null;
		return this.client.ask(question, signal);
	}

	async openQueue(startRun: boolean): Promise<void> {
		if (!(await this.ensureReady())) return;
		if (startRun && !this.runner.active && !(await this.guard('run'))) return; // the window starts the run itself
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
		if (!(await this.guard('add'))) return;
		try {
			const r = await this.client.add(target.url);
			new Notice(r.queued > 0 ? `Queued: ${target.url}` : 'Already in the queue or in your wiki.');
		} catch (e) {
			new Notice(`Could not queue the link: ${e instanceof SbError ? e.message : String(e)}`);
		}
		void this.refreshStatus();
	}

	private async ask(): Promise<void> {
		if (await this.guard('ask')) new AskModal(this.app, this).open();
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
