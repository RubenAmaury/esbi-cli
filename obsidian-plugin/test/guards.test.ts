// The pure parts of the guards: which vault is open, which models send text away, what the modal says.
import { existsSync, mkdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseInfo } from '../src/contract';
import { cloudConfirmation, cloudKey, cloudModels, sameFolder, sendsTextOut, vaultProblem } from '../src/guards';
import { scratchDir } from './helpers';

describe('sameFolder', () => {
	const dir = scratchDir();
	mkdirSync(join(dir, 'vault'));
	symlinkSync(join(dir, 'vault'), join(dir, 'link'));
	mkdirSync(join(dir, 'other'));

	it('sees through symlinks (iCloud and Homebrew paths often are) and trailing slashes', () => {
		expect(sameFolder(join(dir, 'vault'), join(dir, 'link'))).toBe(true);
		expect(sameFolder(join(dir, 'link') + '/', join(dir, 'vault'))).toBe(true);
		expect(sameFolder(join(dir, 'vault') + '//', join(dir, 'vault'))).toBe(true);
	});

	it('sees through a symlinked parent, and "." and ".." segments', () => {
		mkdirSync(join(dir, 'real', 'deep'), { recursive: true });
		symlinkSync(join(dir, 'real'), join(dir, 'via'));
		expect(sameFolder(join(dir, 'via', 'deep'), join(dir, 'real', 'deep'))).toBe(true);
		expect(sameFolder(join(dir, 'real', 'deep', '..', 'deep'), join(dir, 'via', 'deep'))).toBe(true);
	});

	it('tells two different folders apart, also when one only differs by a prefix', () => {
		mkdirSync(join(dir, 'vault2'));
		expect(sameFolder(join(dir, 'vault'), join(dir, 'other'))).toBe(false);
		expect(sameFolder(join(dir, 'vault'), join(dir, 'vault2'))).toBe(false);
	});

	it('is case-insensitive exactly where the volume is (the default macOS volume), and not elsewhere', () => {
		mkdirSync(join(dir, 'MixedCase'));
		const volumeIgnoresCase = existsSync(join(dir, 'MIXEDCASE'));
		expect(sameFolder(join(dir, 'MixedCase'), join(dir, 'MIXEDCASE'))).toBe(volumeIgnoresCase);
	});

	it('does not match a folder that does not exist, nor an empty path, nor a file', () => {
		writeFileSync(join(dir, 'a-file'), '');
		expect(sameFolder(join(dir, 'vault'), join(dir, 'missing'))).toBe(false);
		expect(sameFolder(join(dir, 'missing'), join(dir, 'missing2'))).toBe(false);
		expect(sameFolder('', '')).toBe(false);
		expect(sameFolder(join(dir, 'vault'), '')).toBe(false);
		expect(sameFolder(join(dir, 'a-file'), join(dir, 'vault'))).toBe(false);
	});

	it('compares two paths that cannot be read as text when they are the same (composed or decomposed accents)', () => {
		const composed = '/no/such/dir/café';
		const decomposed = '/no/such/dir/café';
		expect(sameFolder(composed, decomposed)).toBe(true);
		expect(sameFolder(composed + '/', composed)).toBe(true);
	});
});

describe('vaultProblem', () => {
	const dir = scratchDir();
	mkdirSync(join(dir, 'mine'));
	mkdirSync(join(dir, 'theirs'));

	it('is null for the same vault', () => {
		expect(vaultProblem(join(dir, 'mine'), { vault: join(dir, 'mine') + '/', config: '/c/config.toml' })).toBeNull();
	});

	it('names both vaults, the config in use and the setting that fixes it', () => {
		const m = vaultProblem(join(dir, 'mine'), { vault: join(dir, 'theirs'), config: '/c/config.toml' }) ?? '';
		expect(m).toContain(join(dir, 'theirs'));
		expect(m).toContain(join(dir, 'mine'));
		expect(m).toContain('/c/config.toml');
		expect(m).toMatch(/Config file/);
	});

	it('refuses (fails closed) when esbi-cli reports no vault, or the open vault has no folder', () => {
		expect(vaultProblem(join(dir, 'mine'), { vault: '', config: '' })).toMatch(/does not say which vault/);
		expect(vaultProblem(undefined, { vault: join(dir, 'mine'), config: '' })).toMatch(/cannot tell which vault is open/);
	});
});

describe('which models send text out', () => {
	it('treats ollama and lmstudio as local and every other provider, known or not, as sending text away', () => {
		for (const m of ['ollama/llama3.2:latest', 'lmstudio/qwen']) expect(sendsTextOut(m)).toBe(false);
		for (const m of ['anthropic/claude-sonnet-5-5', 'openai/gpt-5', 'claude-cli/default', 'codex-cli/default', 'mystery/x', 'no-provider']) {
			expect(sendsTextOut(m)).toBe(true);
		}
	});

	const models = { summarize: 'anthropic/claude-sonnet-5-5', synthesize: 'ollama/qwen3:4b', private: 'ollama/llama3.2', ask: 'claude-cli/default', embed: 'ollama/nomic-embed-text' };

	it('a run uses every task but ask; an ask uses only the ask task', () => {
		expect(cloudModels(models, 'run')).toEqual([{ task: 'summarize', model: 'anthropic/claude-sonnet-5-5' }]);
		expect(cloudModels(models, 'ask')).toEqual([{ task: 'ask', model: 'claude-cli/default' }]);
		expect(cloudModels({ summarize: 'ollama/x', ask: 'ollama/x' }, 'run')).toEqual([]);
		expect(cloudModels({ summarize: 'anthropic/x', ask: 'ollama/x' }, 'ask')).toEqual([]);
	});

	it('names the models and what leaves the machine, without ever promising email is safe by itself', () => {
		const c = cloudConfirmation('run', cloudModels({ summarize: 'anthropic/claude-sonnet-5-5', synthesize: 'codex-cli/default' }, 'run'));
		const text = [c.title, ...c.lines].join('\n');
		expect(text).toContain('anthropic/claude-sonnet-5-5');
		expect(text).toContain('codex-cli/default');
		expect(text).toMatch(/leave this computer/);
		expect(text).toMatch(/email/i);
		expect(cloudConfirmation('ask', [{ task: 'ask', model: 'claude-cli/default' }]).lines.join('\n')).toMatch(/question/);
	});

	it('the remembered key changes with the scope and with the models', () => {
		const a = cloudModels({ summarize: 'anthropic/x' }, 'run');
		const b = cloudModels({ summarize: 'openai/x' }, 'run');
		expect(cloudKey('run', a)).not.toBe(cloudKey('ask', a));
		expect(cloudKey('run', a)).not.toBe(cloudKey('run', b));
		expect(cloudKey('run', a)).toBe(cloudKey('run', [...a]));
	});
});

describe('parseInfo', () => {
	it('reads the config path and the models, ignoring anything that is not text', () => {
		const i = parseInfo({ vault: '/v', version: '0.3.0', config: '/c.toml', models: { summarize: 'ollama/x', bad: 3, ask: 'ollama/y' } });
		expect(i).toEqual({ vault: '/v', version: '0.3.0', config: '/c.toml', models: { summarize: 'ollama/x', ask: 'ollama/y' } });
		expect(parseInfo({}).models).toEqual({});
	});
});
