import { ChevronDown } from 'lucide-react';

import { getErrorMessage } from '../../../shared/error-message';
import { formatTimestamp } from '../../../shared/format';
import { FilterBar } from '../../../shared/ui/workbench';
import type { MarketPageController } from './market-page-controller';
import { getNoteTypeLabel, getPriorityLabel } from './market-page-format';

export function MarketResearchNotesWorkspace({
  controller,
}: {
  controller: MarketPageController;
}) {
  return (
    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
      <MarketResearchNoteEditor controller={controller} />
      <MarketResearchNoteHistory controller={controller} />
    </div>
  );
}

function MarketResearchNoteEditor({
  controller,
}: {
  controller: MarketPageController;
}) {
  const {
    copy,
    createResearchNote,
    editingNoteId,
    noteContent,
    noteDate,
    notePriority,
    noteTitle,
    noteType,
    pushToast,
    selectedItem,
    setEditingNoteId,
    setNoteContent,
    setNoteDate,
    setNotePriority,
    setNoteTitle,
    setNoteType,
    updateResearchNote,
  } = controller;
  return (
    <div className="app-workbench-section min-w-0 p-4 sm:p-5">
      <div className="app-kicker app-type-overline">
        {copy.market.notesTitle}
      </div>
      {selectedItem ? (
        <form
          className="mt-4 grid gap-3"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!noteTitle.trim() || !noteContent.trim()) {
              pushToast('error', copy.market.noteFailed, copy.common.required);
              return;
            }
            try {
              if (editingNoteId !== null) {
                await updateResearchNote.mutateAsync({
                  noteId: editingNoteId,
                  entry_kind: noteType,
                  title: noteTitle.trim(),
                  content: noteContent.trim(),
                  priority: notePriority,
                  event_date: noteDate || null,
                });
              } else {
                await createResearchNote.mutateAsync({
                  symbol: selectedItem.symbol,
                  asset_class: selectedItem.asset_class,
                  entry_kind: noteType,
                  title: noteTitle.trim(),
                  content: noteContent.trim(),
                  priority: notePriority,
                  event_date: noteDate || null,
                });
              }
              setEditingNoteId(null);
              setNoteType('note');
              setNotePriority('normal');
              setNoteTitle('');
              setNoteContent('');
              setNoteDate('');
              pushToast(
                'success',
                editingNoteId !== null
                  ? copy.market.updateNote
                  : copy.market.noteSaved,
                selectedItem.symbol,
              );
            } catch (error) {
              pushToast(
                'error',
                copy.market.noteFailed,
                getErrorMessage(error),
              );
            }
          }}
        >
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="text-sm font-medium">
                {copy.market.noteType}
              </span>
              <select
                name="research_note_type"
                value={noteType}
                onChange={(event) => setNoteType(event.target.value)}
                className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
              >
                <option value="note">{copy.market.note}</option>
                <option value="thesis">{copy.market.thesis}</option>
                <option value="catalyst">{copy.market.catalyst}</option>
              </select>
            </label>
            <label className="grid gap-2">
              <span className="text-sm font-medium">
                {copy.market.notePriority}
              </span>
              <select
                name="research_note_priority"
                value={notePriority}
                onChange={(event) => setNotePriority(event.target.value)}
                className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
              >
                <option value="high">{copy.market.highPriority}</option>
                <option value="normal">{copy.market.normalPriority}</option>
                <option value="low">{copy.market.lowPriority}</option>
              </select>
            </label>
          </div>
          <label className="grid gap-2">
            <span className="text-sm font-medium">{copy.market.noteTitle}</span>
            <input
              name="research_note_title"
              autoComplete="off"
              value={noteTitle}
              onChange={(event) => setNoteTitle(event.target.value)}
              placeholder={copy.market.noteTitlePlaceholder}
              className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
            />
          </label>
          <label className="grid gap-2">
            <span className="text-sm font-medium">
              {copy.market.noteContent}
            </span>
            <textarea
              name="research_note_content"
              value={noteContent}
              onChange={(event) => setNoteContent(event.target.value)}
              placeholder={copy.market.noteContentPlaceholder}
              rows={5}
              className="app-field min-h-32 rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
            />
          </label>
          <label className="grid gap-2">
            <span className="text-sm font-medium">{copy.market.noteDate}</span>
            <input
              name="research_note_date"
              type="date"
              value={noteDate}
              onChange={(event) => setNoteDate(event.target.value)}
              className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={
              createResearchNote.isPending || updateResearchNote.isPending
            }
            className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm"
          >
            {createResearchNote.isPending || updateResearchNote.isPending
              ? copy.market.savingNote
              : editingNoteId !== null
                ? copy.market.updateNote
                : copy.market.saveNote}
          </button>
        </form>
      ) : (
        <div className="app-muted mt-4 text-sm">{copy.market.noSelection}</div>
      )}
    </div>
  );
}

function MarketResearchNoteHistory({
  controller,
}: {
  controller: MarketPageController;
}) {
  const {
    copy,
    deleteResearchNote,
    noteFilterDateFrom,
    noteFilterDateTo,
    noteFilterPriority,
    noteFilterType,
    notes,
    pushToast,
    setEditingNoteId,
    setNoteContent,
    setNoteDate,
    setNoteFilterDateFrom,
    setNoteFilterDateTo,
    setNoteFilterPriority,
    setNoteFilterType,
    setNotePriority,
    setNoteTitle,
    setNoteType,
  } = controller;
  return (
    <div className="app-workbench-section min-w-0 p-4 sm:p-5">
      <div className="app-kicker app-type-overline">
        {copy.market.notesTitle}
      </div>
      <FilterBar
        className="mt-4"
        label={copy.market.notesTitle}
        summary={
          notes.data
            ? `${notes.data.items.length} ${copy.market.researchCount}`
            : undefined
        }
      >
        <label className="grid gap-2">
          <span className="text-sm font-medium">{copy.market.noteType}</span>
          <select
            value={noteFilterType}
            onChange={(event) => setNoteFilterType(event.target.value)}
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          >
            <option value="">{copy.market.allTypes}</option>
            <option value="note">{copy.market.note}</option>
            <option value="thesis">{copy.market.thesis}</option>
            <option value="catalyst">{copy.market.catalyst}</option>
          </select>
        </label>
        <label className="grid gap-2">
          <span className="text-sm font-medium">
            {copy.market.notePriority}
          </span>
          <select
            value={noteFilterPriority}
            onChange={(event) => setNoteFilterPriority(event.target.value)}
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          >
            <option value="">{copy.market.allPriorities}</option>
            <option value="high">{copy.market.highPriority}</option>
            <option value="normal">{copy.market.normalPriority}</option>
            <option value="low">{copy.market.lowPriority}</option>
          </select>
        </label>
        <label className="grid gap-2">
          <span className="text-sm font-medium">
            {copy.market.noteDateFrom}
          </span>
          <input
            type="date"
            value={noteFilterDateFrom}
            onChange={(event) => setNoteFilterDateFrom(event.target.value)}
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
            aria-label={copy.market.noteDateFrom}
          />
        </label>
        <label className="grid gap-2">
          <span className="text-sm font-medium">{copy.market.noteDateTo}</span>
          <input
            type="date"
            value={noteFilterDateTo}
            onChange={(event) => setNoteFilterDateTo(event.target.value)}
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
            aria-label={copy.market.noteDateTo}
          />
        </label>
      </FilterBar>
      {notes.isLoading ? (
        <div className="app-muted mt-4 text-sm">{copy.states.loading}</div>
      ) : notes.isError ? (
        <div className="app-muted mt-4 text-sm">{copy.market.noteFailed}</div>
      ) : notes.data && notes.data.items.length > 0 ? (
        <div className="mt-4 grid gap-3">
          {notes.data.items.map((note) => (
            <div
              key={note.id}
              className="app-panel-strong rounded-[var(--app-radius-surface)] px-4 py-4"
            >
              <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="text-sm font-semibold">{note.title}</div>
                  <div className="app-kicker app-type-overline mt-2">
                    {getNoteTypeLabel(copy, note.entry_kind)} ·{' '}
                    {getPriorityLabel(copy, note.priority)}
                    {note.event_date ? ` · ${note.event_date}` : ''}
                  </div>
                  <div className="app-kicker app-type-overline mt-2">
                    {copy.market.noteUpdatedAt} ·{' '}
                    <time dateTime={note.updated_at}>
                      {formatTimestamp(note.updated_at)}
                    </time>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    type="button"
                    className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs sm:min-h-8"
                    onClick={() => {
                      setEditingNoteId(note.id);
                      setNoteType(note.entry_kind);
                      setNotePriority(note.priority);
                      setNoteTitle(note.title);
                      setNoteContent(note.content);
                      setNoteDate(note.event_date ?? '');
                    }}
                  >
                    {copy.market.editNote}
                  </button>
                  <button
                    type="button"
                    className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs sm:min-h-8"
                    onClick={async () => {
                      try {
                        await deleteResearchNote.mutateAsync(note.id);
                        pushToast(
                          'success',
                          copy.market.noteDeleted,
                          note.title,
                        );
                      } catch (error) {
                        pushToast(
                          'error',
                          copy.market.noteDeleteFailed,
                          getErrorMessage(error),
                        );
                      }
                    }}
                  >
                    {copy.market.remove}
                  </button>
                </div>
              </div>
              <details
                className="group mt-3 border-t border-[var(--app-divider)]"
                data-testid={`market-research-note-disclosure-${note.id}`}
              >
                <summary className="app-focus-ring app-muted flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--app-radius-control)] py-2 text-sm font-semibold sm:min-h-8 [&::-webkit-details-marker]:hidden">
                  <span className="group-open:hidden">
                    {copy.market.showFullNote}
                  </span>
                  <span className="hidden group-open:inline">
                    {copy.market.hideFullNote}
                  </span>
                  <ChevronDown
                    aria-hidden="true"
                    className="size-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"
                  />
                </summary>
                <div
                  className="app-muted whitespace-pre-wrap break-words border-t border-[var(--app-divider)] pt-3 text-sm leading-6"
                  data-testid={`market-research-note-content-${note.id}`}
                >
                  {note.content}
                </div>
              </details>
            </div>
          ))}
        </div>
      ) : (
        <div className="app-muted mt-4 text-sm">{copy.market.notesEmpty}</div>
      )}
    </div>
  );
}
