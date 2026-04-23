import createClient from 'openapi-fetch';
import type { paths } from './schema';

// Base URL defaults to the local dev API server.
// Override with VITE_API_BASE_URL environment variable.
const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const client = createClient<paths>({ baseUrl });
