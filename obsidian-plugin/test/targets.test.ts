import { describe, expect, it } from 'vitest';
import { dailyIndexPath, parseWebUrl, pickTarget, urlFromSelection } from '../src/targets';

describe('parseWebUrl', () => {
	it('accepts http and https', () => {
		expect(parseWebUrl(' https://example.com/a?b=1#c ')).toBe('https://example.com/a?b=1#c');
		expect(parseWebUrl('http://example.com')).toBe('http://example.com/');
	});
	it('rejects other schemes, credentials, sentences and junk', () => {
		for (const bad of ['mail:abc@example.com', 'file:///etc/passwd', 'javascript:alert(1)', 'obsidian://open?vault=x', 'ftp://x.com/a']) {
			expect(parseWebUrl(bad), bad).toBeNull();
		}
		expect(parseWebUrl('https://user:secret@example.com/a')).toBeNull();
		expect(parseWebUrl('see https://example.com now')).toBeNull();
		expect(parseWebUrl('')).toBeNull();
		expect(parseWebUrl('not a url')).toBeNull();
	});
});

describe('urlFromSelection', () => {
	it('reads a bare URL, an angle link and a Markdown link', () => {
		expect(urlFromSelection('https://example.com/x')).toBe('https://example.com/x');
		expect(urlFromSelection('<https://example.com/x>')).toBe('https://example.com/x');
		expect(urlFromSelection('[A title](https://example.com/x)')).toBe('https://example.com/x');
		expect(urlFromSelection('[A title](https://example.com/x "tip")')).toBe('https://example.com/x');
	});
	it('does not take a URL out of a longer text', () => {
		expect(urlFromSelection('read [this](https://a.com) and [that](https://b.com)')).toBeNull();
	});
});

describe('pickTarget', () => {
	it('prefers the selection', () => {
		expect(pickTarget({ selection: 'https://a.com', source: 'https://b.com' })).toEqual({ url: 'https://a.com/' });
	});
	it('does not fall back to the note when the selection is not a link', () => {
		expect(pickTarget({ selection: 'some words', source: 'https://b.com' })).toHaveProperty('problem');
	});
	it('uses the note source when nothing is selected', () => {
		expect(pickTarget({ selection: '  ', source: 'https://b.com/p' })).toEqual({ url: 'https://b.com/p' });
	});
	it('refuses an email note: its source is a mail id, and it must never be re-sent anywhere', () => {
		const t = pickTarget({ selection: '', source: 'mail:<abc@mail.gmail.com>' });
		expect(t).toHaveProperty('problem');
	});
	it('explains when there is nothing to queue', () => {
		expect(pickTarget({ selection: '', source: undefined })).toHaveProperty('problem');
		expect(pickTarget({ selection: '', source: ['x'] })).toHaveProperty('problem');
	});
});

describe('dailyIndexPath', () => {
	it('uses the local calendar day, zero padded', () => {
		expect(dailyIndexPath(new Date(2026, 0, 5, 23, 59))).toBe('wiki/daily/2026-01-05.md');
		expect(dailyIndexPath(new Date(2026, 9, 14, 0, 1))).toBe('wiki/daily/2026-10-14.md');
	});
});
