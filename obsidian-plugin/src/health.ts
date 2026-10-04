import { PLUGIN_CONTRACT, SbError, type VersionInfo } from './contract';

export const SITE_URL = 'https://rubenamaury.github.io/esbi-cli/';
export const INSTALL_BREW = 'brew install rubenamaury/esbi-cli/esbi-cli';
export const INSTALL_UV = 'uv tool install git+https://github.com/RubenAmaury/esbi-cli';
export const UPGRADE_CMD = 'sb update';

export type Health = ({ ok: true } & VersionInfo) | { ok: false; error: SbError };

/** Runs `sb version --json` once. Never throws: a broken setup is a result, not a crash. */
export async function checkHealth(client: { version: () => Promise<VersionInfo> }): Promise<Health> {
	try {
		const v = await client.version();
		if (v.contract > PLUGIN_CONTRACT) {
			return { ok: false, error: new SbError('too_new', `esbi-cli speaks contract ${v.contract}; this plugin understands ${PLUGIN_CONTRACT}.`) };
		}
		return { ok: true, ...v };
	} catch (e) {
		return { ok: false, error: e instanceof SbError ? e : new SbError('bad_output', e instanceof Error ? e.message : String(e)) };
	}
}

export interface Explanation {
	title: string;
	/** What the user should do, one line each. Commands are shown in code style by the UI. */
	steps: string[];
	/** Commands the UI offers to copy. */
	commands: string[];
}

/** One clear message with what to do, per kind of failure. The plugin never runs these commands itself. */
export function explain(e: SbError): Explanation {
	switch (e.kind) {
		case 'missing':
		case 'spawn':
			return {
				title: 'esbi-cli is not installed, or the plugin cannot find it.',
				steps: [
					'Install it with Homebrew or uv, then press Test connection in the plugin settings.',
					'Already installed? Set the full path to sb in the plugin settings (run "which sb" in a terminal).',
					`More: ${SITE_URL}`,
				],
				commands: [INSTALL_BREW, INSTALL_UV],
			};
		case 'old':
			return {
				title: 'This version of esbi-cli is too old for the plugin (it has no --json output).',
				steps: ['Update esbi-cli, then press Test connection.', `More: ${SITE_URL}`],
				commands: [UPGRADE_CMD],
			};
		case 'too_new':
			return {
				title: 'esbi-cli is newer than this plugin understands.',
				steps: ['Update the plugin: Settings, Community plugins, Check for updates (or install the latest release again).'],
				commands: [],
			};
		case 'timeout':
			return { title: 'esbi-cli did not answer in time.', steps: ['Try again. If it keeps happening, run "sb doctor" in a terminal.'], commands: ['sb doctor'] };
		case 'failed':
			return { title: e.message, steps: ['Run Check setup from the command palette for details.'], commands: [] };
		default:
			return { title: 'esbi-cli gave an answer the plugin cannot read.', steps: [e.message, 'Check that the path in the plugin settings points to sb.'], commands: [] };
	}
}
