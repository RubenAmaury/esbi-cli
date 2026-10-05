import { homedir } from 'os';
import { PluginSettingTab, Setting, type App } from 'obsidian';
import { SbError } from '../contract';
import { checkHealth, explain, INSTALL_BREW, INSTALL_UV } from '../health';
import { detectSb } from '../locate';
import type EsbiPlugin from '../main';
import { MIN_REFRESH_SECONDS } from '../settings';
import { vaultProblem } from '../guards';
import { commandRow } from './problem';

export class EsbiSettingTab extends PluginSettingTab {
	constructor(
		app: App,
		private readonly plugin: EsbiPlugin,
	) {
		super(app, plugin);
	}

	display(): void {
		const { containerEl } = this;
		containerEl.empty();
		const s = this.plugin.settings;

		new Setting(containerEl)
			.setName('Path to the sb command')
			.setDesc('Stored on this device only. Leave empty to let your login shell find it.')
			.addText((t) =>
				t.setPlaceholder('Automatic').setValue(s.sbPath).onChange(async (v) => {
					s.sbPath = v.trim();
					await this.plugin.saveSettings();
				}),
			)
			.addButton((b) =>
				b.setButtonText('Detect').onClick(async () => {
					const found = await detectSb(homedir());
					if (found) {
						s.sbPath = found;
						await this.plugin.saveSettings();
						this.display();
					} else {
						this.result('Could not find sb. Install esbi-cli first (see below), or type its path.', true);
					}
				}),
			);

		new Setting(containerEl)
			.setName('Config file')
			.setDesc('Optional. Passed to sb as --config. Stored on this device only.')
			.addText((t) =>
				t.setPlaceholder('/Users/you/.config/esbi-cli/config.toml').setValue(s.configPath).onChange(async (v) => {
					s.configPath = v.trim();
					await this.plugin.saveSettings();
				}),
			);

		new Setting(containerEl)
			.setName('Status bar refresh (seconds)')
			.setDesc(`How often the queue count is read. Minimum ${MIN_REFRESH_SECONDS}.`)
			.addText((t) =>
				t.setValue(String(s.statusRefreshSeconds)).onChange(async (v) => {
					const n = Number(v);
					if (!Number.isFinite(n)) return;
					s.statusRefreshSeconds = n;
					await this.plugin.saveSettings();
				}),
			);

		new Setting(containerEl)
			.setName('Test connection')
			.setDesc('Runs the version command and shows the version and the contract number.')
			.addButton((b) => b.setButtonText('Test').setCta().onClick(() => void this.test()));

		this.resultEl = containerEl.createDiv({ cls: 'esbi-result' });

		new Setting(containerEl).setName('Installation help').setHeading();
		containerEl.createEl('p', { text: 'The plugin does not install anything. If you do not have the sb command yet, run one of these in a terminal:' });
		commandRow(containerEl, INSTALL_BREW);
		commandRow(containerEl, INSTALL_UV);
	}

	private resultEl!: HTMLElement;

	private result(text: string, bad = false): void {
		this.resultEl.empty();
		this.resultEl.createEl('p', { text, cls: bad ? 'esbi-error' : 'esbi-ok' });
	}

	private async test(): Promise<void> {
		this.result('Testing...');
		const h = await checkHealth(this.plugin.client);
		this.plugin.health = h;
		if (!h.ok) {
			const x = explain(h.error);
			this.result([x.title, ...x.steps].join(' '), true);
			return;
		}
		let line = `Connected: esbi-cli ${h.version}, contract ${h.contract}.`;
		try {
			const info = await this.plugin.client.info();
			const problem = vaultProblem(this.plugin.vaultFolder(), info);
			if (problem) line += ` Warning: ${problem} Add, Run and Ask refuse to work until this is fixed.`;
		} catch (e) {
			if (!(e instanceof SbError)) throw e; // no config yet: not a connection problem
		}
		this.result(line);
		void this.plugin.refreshStatus();
	}
}
