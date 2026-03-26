import type { CustomAppDef } from '../../types';

export interface FormData {
  display_name: string;
  default_port: string;
  scheme: string;
  version_path: string;
  github_repo: string;
  accepts_api_key: boolean;
  auth_header: string;
  aliases: string;
  docker_images: string;
  version_keys: string;
  strip_v: boolean;
}

export interface FormErrors {
  [key: string]: string | undefined;
}

export interface ValidationResult {
  errors: FormErrors;
  warnings: FormErrors;
  valid: boolean;
}

export function validateCustomApp(
  form: FormData,
  existingApps: CustomAppDef[],
  editingName: string | null,
): ValidationResult {
  const errors: FormErrors = {};
  const warnings: FormErrors = {};

  if (!form.display_name.trim()) {
    errors.display_name = 'Display name is required.';
  } else {
    const dup = existingApps.find(
      (a) => a.display_name.toLowerCase() === form.display_name.trim().toLowerCase()
        && a.name !== editingName
    );
    if (dup) warnings.display_name = 'Another custom app has this display name. Consider a more specific name.';
  }

  const port = parseInt(form.default_port, 10);
  if (!form.default_port || isNaN(port) || port < 1 || port > 65535) {
    errors.default_port = 'Port must be a number between 1 and 65535.';
  }

  if (form.version_path && !form.version_path.startsWith('/')) {
    errors.version_path = 'Path must start with /. Example: /api/version';
  }

  if (form.github_repo) {
    const repo = form.github_repo.trim();
    if (!repo.includes('github.com') && !repo.startsWith('http') && !/^[^\s/]+\/[^\s/]+$/.test(repo)) {
      errors.github_repo = "Use owner/repo format or a full GitHub URL. Example: mealie-recipes/mealie";
    }
  }

  if (form.accepts_api_key && !form.auth_header.trim()) {
    errors.auth_header = 'Enter the header name, or uncheck the checkbox.';
  }

  return {
    errors,
    warnings,
    valid: Object.keys(errors).length === 0,
  };
}
