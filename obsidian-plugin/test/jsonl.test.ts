import { describe, expect, it } from 'vitest';
import { LineSplitter, lastObject, parseObject } from '../src/jsonl';

describe('LineSplitter', () => {
	it('holds a partial line until its newline arrives', () => {
		const s = new LineSplitter();
		expect(s.push('{"event":"sta')).toEqual([]);
		expect(s.push('rted"}\n{"event"')).toEqual(['{"event":"started"}']);
		expect(s.push(':"finished"}\n')).toEqual(['{"event":"finished"}']);
		expect(s.flush()).toEqual([]);
	});

	it('flushes a final line that has no newline', () => {
		const s = new LineSplitter();
		s.push('{"a":1}\n{"b":2}');
		expect(s.flush()).toEqual(['{"b":2}']);
	});

	it('accepts CRLF and drops blank lines', () => {
		const s = new LineSplitter();
		expect(s.push('{"a":1}\r\n\r\n{"b":2}\r\n')).toEqual(['{"a":1}', '{"b":2}']);
	});
});

describe('parseObject', () => {
	it('parses an object, including unicode', () => {
		expect(parseObject('{"title":"Año 2026: 日本語 🙂"}')).toEqual({ title: 'Año 2026: 日本語 🙂' });
	});

	it('rejects invalid JSON, arrays and scalars instead of throwing', () => {
		expect(parseObject('not json')).toBeNull();
		expect(parseObject('{"a":')).toBeNull();
		expect(parseObject('[1,2]')).toBeNull();
		expect(parseObject('42')).toBeNull();
		expect(parseObject('null')).toBeNull();
		expect(parseObject('')).toBeNull();
	});
});

describe('lastObject', () => {
	it('skips login-shell noise before the JSON', () => {
		expect(lastObject(['Welcome back!', '{"contract":1}'])).toEqual({ contract: 1 });
	});

	it('takes the last object when there are several', () => {
		expect(lastObject(['{"a":1}', '{"a":2}'])).toEqual({ a: 2 });
	});

	it('returns null when nothing parses', () => {
		expect(lastObject(['hello', 'world'])).toBeNull();
	});
});
