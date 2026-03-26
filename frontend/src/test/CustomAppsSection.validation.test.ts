import { describe, it, expect } from 'vitest';
import { validateCustomApp, type FormData } from '../components/settings/customAppsValidation';
import type { CustomAppDef } from '../types';

function makeForm(overrides: Partial<FormData> = {}): FormData {
  return {
    display_name: 'My App',
    default_port: '8080',
    scheme: 'http',
    version_path: '/api/version',
    github_repo: 'owner/repo',
    accepts_api_key: false,
    auth_header: '',
    aliases: '',
    docker_images: '',
    version_keys: 'version',
    strip_v: false,
    ...overrides,
  };
}

const NO_APPS: CustomAppDef[] = [];

describe('validateCustomApp', () => {
  // --- display_name ---
  it('requires display_name', () => {
    const r = validateCustomApp(makeForm({ display_name: '' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.display_name).toBeDefined();
  });

  it('requires display_name (whitespace only)', () => {
    const r = validateCustomApp(makeForm({ display_name: '   ' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.display_name).toBeDefined();
  });

  it('warns on duplicate display_name', () => {
    const existing: CustomAppDef[] = [
      { name: 'existing', display_name: 'My App', default_port: 80, scheme: 'http', version_path: null, github_repo: null, aliases: [], docker_images: [], accepts_api_key: false, auth_header: null, version_keys: ['version'], strip_v: false },
    ];
    const r = validateCustomApp(makeForm({ display_name: 'My App' }), existing, null);
    // Should be valid (warning, not error)
    expect(r.valid).toBe(true);
    expect(r.warnings.display_name).toBeDefined();
  });

  it('does not warn on duplicate when editing the same app', () => {
    const existing: CustomAppDef[] = [
      { name: 'existing', display_name: 'My App', default_port: 80, scheme: 'http', version_path: null, github_repo: null, aliases: [], docker_images: [], accepts_api_key: false, auth_header: null, version_keys: ['version'], strip_v: false },
    ];
    const r = validateCustomApp(makeForm({ display_name: 'My App' }), existing, 'existing');
    expect(r.warnings.display_name).toBeUndefined();
  });

  // --- port ---
  it('rejects empty port', () => {
    const r = validateCustomApp(makeForm({ default_port: '' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.default_port).toBeDefined();
  });

  it('rejects port 0', () => {
    const r = validateCustomApp(makeForm({ default_port: '0' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.default_port).toBeDefined();
  });

  it('accepts port 1', () => {
    const r = validateCustomApp(makeForm({ default_port: '1' }), NO_APPS, null);
    expect(r.errors.default_port).toBeUndefined();
  });

  it('accepts port 65535', () => {
    const r = validateCustomApp(makeForm({ default_port: '65535' }), NO_APPS, null);
    expect(r.errors.default_port).toBeUndefined();
  });

  it('rejects port 65536', () => {
    const r = validateCustomApp(makeForm({ default_port: '65536' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.default_port).toBeDefined();
  });

  it('rejects negative port', () => {
    const r = validateCustomApp(makeForm({ default_port: '-1' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.default_port).toBeDefined();
  });

  it('rejects non-numeric port', () => {
    const r = validateCustomApp(makeForm({ default_port: 'abc' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.default_port).toBeDefined();
  });

  // --- version_path ---
  it('accepts version_path starting with /', () => {
    const r = validateCustomApp(makeForm({ version_path: '/api/version' }), NO_APPS, null);
    expect(r.errors.version_path).toBeUndefined();
  });

  it('rejects version_path not starting with /', () => {
    const r = validateCustomApp(makeForm({ version_path: 'api/version' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.version_path).toBeDefined();
  });

  it('allows empty version_path', () => {
    const r = validateCustomApp(makeForm({ version_path: '' }), NO_APPS, null);
    expect(r.errors.version_path).toBeUndefined();
  });

  // --- github_repo ---
  it('accepts owner/repo format', () => {
    const r = validateCustomApp(makeForm({ github_repo: 'mealie-recipes/mealie' }), NO_APPS, null);
    expect(r.errors.github_repo).toBeUndefined();
  });

  it('accepts full GitHub URL', () => {
    const r = validateCustomApp(makeForm({ github_repo: 'https://github.com/mealie-recipes/mealie' }), NO_APPS, null);
    expect(r.errors.github_repo).toBeUndefined();
  });

  it('accepts github.com URL without https', () => {
    const r = validateCustomApp(makeForm({ github_repo: 'github.com/owner/repo' }), NO_APPS, null);
    expect(r.errors.github_repo).toBeUndefined();
  });

  it('rejects garbage github_repo', () => {
    const r = validateCustomApp(makeForm({ github_repo: 'just-a-word' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.github_repo).toBeDefined();
  });

  it('allows empty github_repo', () => {
    const r = validateCustomApp(makeForm({ github_repo: '' }), NO_APPS, null);
    expect(r.errors.github_repo).toBeUndefined();
  });

  // --- auth_header ---
  it('requires auth_header when accepts_api_key is true', () => {
    const r = validateCustomApp(makeForm({ accepts_api_key: true, auth_header: '' }), NO_APPS, null);
    expect(r.valid).toBe(false);
    expect(r.errors.auth_header).toBeDefined();
  });

  it('accepts auth_header when accepts_api_key is true and header provided', () => {
    const r = validateCustomApp(makeForm({ accepts_api_key: true, auth_header: 'X-Api-Key' }), NO_APPS, null);
    expect(r.errors.auth_header).toBeUndefined();
  });

  it('does not require auth_header when accepts_api_key is false', () => {
    const r = validateCustomApp(makeForm({ accepts_api_key: false, auth_header: '' }), NO_APPS, null);
    expect(r.errors.auth_header).toBeUndefined();
  });

  // --- valid form ---
  it('returns valid for a complete correct form', () => {
    const r = validateCustomApp(makeForm(), NO_APPS, null);
    expect(r.valid).toBe(true);
    expect(Object.keys(r.errors)).toHaveLength(0);
  });
});
