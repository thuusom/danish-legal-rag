import { Marked } from 'marked';
import DOMPurify from 'dompurify';

// Pre-configured marked instance with GFM tables and line breaks enabled
const marked = new Marked({
	gfm: true,
	breaks: true
});

/**
 * Parse markdown to sanitised HTML.
 * Safe for use with Svelte's {@html} directive.
 */
export function renderMarkdown(source: string): string {
	const raw = marked.parse(source) as string;
	return DOMPurify.sanitize(raw);
}
