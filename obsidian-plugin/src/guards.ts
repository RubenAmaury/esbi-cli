import { statSync } from 'fs';
import { resolve } from 'path';
import type { InfoInfo } from './contract';

/** True when both paths are the same existing folder, whatever way each was spelled. */
export function sameFolder(a: string, b: string): boolean {
	if (a.trim() === '' || b.trim() === '') return false;
	// The folder's identity (device and inode) sees through symlinks (iCloud, Homebrew), a symlinked parent, ".." segments,
	// trailing slashes, and a case-insensitive volume (the macOS default), which no string comparison can promise.
	try {
		const x = statSync(a, { bigint: true });
		const y = statSync(b, { bigint: true });
		return x.isDirectory() && y.isDirectory() && x.dev === y.dev && x.ino === y.ino;
	} catch {
		// One of them is not there: it cannot be the open vault. Two spellings of one missing path still compare equal.
		return resolve(a).normalize('NFC') === resolve(b).normalize('NFC');
	}
}

/** Why a command must not run, or null when the vault sb uses is the one open in Obsidian. Fails closed. */
export function vaultProblem(openVault: string | undefined, info: Pick<InfoInfo, 'vault' | 'config'>): string | null {
	if (info.vault === '') return 'esbi-cli does not say which vault it uses. Run Check setup.';
	if (!openVault) return 'The plugin cannot tell which vault is open in Obsidian.';
	if (sameFolder(openVault, info.vault)) return null;
	return (
		`esbi-cli is set up for the vault ${info.vault}` +
		(info.config ? ` (config ${info.config})` : '') +
		`, but the vault open in Obsidian is ${openVault}. ` +
		'Fix: in Settings, esbi-cli, set Config file to the config.toml of this vault.'
	);
}

/**
 * Providers that run on this computer. Every other provider (openai, anthropic, claude-cli, codex-cli, and any
 * provider this list does not know) is treated as sending text away: the plugin fails closed.
 * Mirrors esbi-cli's `sends_text_out`; `sb info --json` does not say it per model yet, so it is derived from the
 * "<provider>/<name>" prefix. Known gap: an ollama or lmstudio model served from another machine looks local here.
 */
const LOCAL_PROVIDERS = ['ollama', 'lmstudio'];

export const sendsTextOut = (model: string): boolean => !LOCAL_PROVIDERS.includes(model.split('/')[0] ?? '');

export type CloudScope = 'run' | 'ask';
export interface CloudModel {
	task: string;
	model: string;
}

/** The models of the tasks a command uses that send text away. A run uses every task but ask; ask uses its own. */
export function cloudModels(models: Record<string, string>, scope: CloudScope): CloudModel[] {
	return Object.entries(models)
		.filter(([task, model]) => (scope === 'ask' ? task === 'ask' : task !== 'ask') && sendsTextOut(model))
		.map(([task, model]) => ({ task, model }));
}

/** What is remembered for the session: the command and the exact models, so a changed model is asked about again. */
export const cloudKey = (scope: CloudScope, cloud: CloudModel[]): string =>
	`${scope}|${cloud.map((c) => `${c.task}=${c.model}`).sort().join(',')}`;

const WHERE: Record<string, string> = {
	anthropic: 'the Anthropic API',
	openai: 'an OpenAI-compatible server (OpenAI, unless esbi-cli is set to another address)',
	'claude-cli': 'Anthropic, through your Claude subscription (the claude command)',
	'codex-cli': 'OpenAI, through your ChatGPT plan (the codex command)',
};

export function cloudConfirmation(scope: CloudScope, cloud: CloudModel[]): { title: string; lines: string[] } {
	const models = cloud.map((c) => `${c.task}: ${c.model} (to ${WHERE[c.model.split('/')[0] ?? ''] ?? 'a service outside this computer'})`);
	const sent =
		scope === 'ask'
			? 'Your question and the text of the wiki pages found for it will leave this computer.'
			: 'The text of the sources in the queue (web pages, PDFs) and of the wiki pages used to relate them will leave this computer.';
	return {
		title: scope === 'ask' ? 'Ask with a cloud model?' : 'Run the queue with a cloud model?',
		lines: [
			'esbi-cli is set to use a model that sends text to another service:',
			...models,
			sent,
			'Notes that came from email are never sent to such a model: esbi-cli refuses.',
			'You are asked once per session for these models. Cancel does nothing.',
		],
	};
}
