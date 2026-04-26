import { describe, it, expect } from 'vitest';
import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
	it('renders bold text', () => {
		const html = renderMarkdown('**fed tekst**');
		expect(html).toContain('<strong>fed tekst</strong>');
	});

	it('renders headings', () => {
		const html = renderMarkdown('## Overskrift');
		expect(html).toContain('<h2');
		expect(html).toContain('Overskrift');
	});

	it('renders unordered lists', () => {
		const html = renderMarkdown('- punkt 1\n- punkt 2');
		expect(html).toContain('<ul>');
		expect(html).toContain('<li>punkt 1</li>');
	});

	it('renders GFM tables', () => {
		const md = '| Kolonne A | Kolonne B |\n|---|---|\n| 1 | 2 |';
		const html = renderMarkdown(md);
		expect(html).toContain('<table>');
		expect(html).toContain('<th>Kolonne A</th>');
		expect(html).toContain('<td>1</td>');
	});

	it('sanitises script tags (XSS prevention)', () => {
		const html = renderMarkdown('<script>alert("xss")</script>');
		expect(html).not.toContain('<script>');
	});

	it('strips onerror attributes', () => {
		const html = renderMarkdown('<img src=x onerror="alert(1)">');
		expect(html).not.toContain('onerror');
	});

	it('renders inline code', () => {
		const html = renderMarkdown('Brug `§ 40 C`');
		expect(html).toContain('<code>');
		expect(html).toContain('§ 40 C');
	});

	it('returns empty string for empty input', () => {
		expect(renderMarkdown('')).toBe('');
	});
});
