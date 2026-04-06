import type { Guest } from '../types';
import { isEligible } from './BulkProgressModal';

interface Props {
  selectionSize: number;
  selectedGuests: Guest[];
  onOsUpdate: () => void;
  onAppUpdate: () => void;
  onClear: () => void;
}

export default function BulkActionBar({ selectionSize, selectedGuests, onOsUpdate, onAppUpdate, onClear }: Props) {
  const osEligible = selectedGuests.filter(g => isEligible(g, 'os_update')).length;
  const appEligible = selectedGuests.filter(g => isEligible(g, 'app_update')).length;
  const osSkipped = selectionSize - osEligible;
  const appSkipped = selectionSize - appEligible;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 bg-gray-900 border-t border-gray-700 px-4 py-3 flex items-center gap-4 flex-wrap">
      <span className="text-sm text-gray-300">{selectionSize} guest{selectionSize !== 1 ? 's' : ''} selected</span>
      <div className="flex items-center gap-2 ml-auto flex-wrap">
        <button
          type="button"
          onClick={onOsUpdate}
          disabled={osEligible === 0}
          title={osEligible === 0 ? 'No selected guests are eligible for OS update' : osSkipped > 0 ? `${osSkipped} will be skipped (not LXC or not running)` : undefined}
          className="px-4 py-1.5 text-sm rounded bg-cyan-700 hover:bg-cyan-600 text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          OS Update{osSkipped > 0 && osEligible > 0 ? ` (${osEligible})` : ''}
        </button>
        <button
          type="button"
          onClick={onAppUpdate}
          disabled={appEligible === 0}
          title={appEligible === 0 ? 'None of the selected guests support app updates' : appSkipped > 0 ? `${appSkipped} will be skipped` : undefined}
          className="px-4 py-1.5 text-sm rounded bg-teal-700 hover:bg-teal-600 text-white disabled:opacity-40 disabled:cursor-not-allowed"
        >
          App Update{appSkipped > 0 && appEligible > 0 ? ` (${appEligible})` : ''}
        </button>
        <button type="button" onClick={onClear} className="text-sm text-gray-400 hover:text-white px-2">
          Clear
        </button>
      </div>
    </div>
  );
}
