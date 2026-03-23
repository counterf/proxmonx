import PasswordField from '../setup/PasswordField';

interface GitHubSectionProps {
  githubToken: string;
  onGithubTokenChange: (v: string) => void;
  disabled?: boolean;
}

export default function GitHubSection({
  githubToken,
  onGithubTokenChange,
}: GitHubSectionProps) {
  return (
    <div className="p-4 rounded bg-surface border border-gray-800">
      <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">GitHub Token</h2>
      <p className="text-xs text-gray-500 mb-3">
        A personal access token increases the GitHub API rate limit from 60 to 5,000 req/hr.
        Leave blank for unauthenticated access.
      </p>
      <PasswordField
        id="s_github_token"
        label="GitHub Token"
        value={githubToken}
        onChange={onGithubTokenChange}
        hint="Optional"
      />
    </div>
  );
}
