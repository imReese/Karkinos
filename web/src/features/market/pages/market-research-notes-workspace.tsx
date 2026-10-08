import { useEffect, useState } from 'react';
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
    <section
      className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-4"
      data-testid="market-research-workspace"
    >
      <MarketResearchNoteEditor controller={controller} />
      <MarketResearchNoteHistory controller={controller} />
    </section>
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
    deleteResearchNote,
    resetNoteEditor,
    editingNoteId,
    noteContent,
    noteDate,
    notePriority,
    noteTitle,
    noteType,
    pushToast,
    selectedItem,
    setNoteContent,
    setNoteDate,
    setNotePriority,
    setNoteTitle,
    setNoteType,
    updateResearchNote,
  } = controller;
  const mutationPending =
    createResearchNote.isPending ||
    updateResearchNote.isPending ||
    deleteResearchNote.isPending;
  return (
    <details
      id="market-research-note-editor"
      open={editingNoteId !== null ? true : undefined}
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid="market-research-note-editor"
    >
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-4 px-1 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:px-2 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="text-sm font-semibold text-[var(--app-text)]">
            {editingNoteId !== null
              ? copy.market.updateNote
              : copy.market.saveNote}
          </span>
          <span className="app-type-micro mt-0.5 block text-[var(--app-text-tertiary)]">
            {selectedItem
              ? [
                  selectedItem.name || selectedItem.symbol,
                  selectedItem.symbol,
                ].join(' · ')
              : copy.market.noSelection}
          </span>
        </span>
        <ChevronDown
          aria-hidden="true"
          className="size-4 shrink-0 text-[var(--app-text-tertiary)] transition-transform group-open:rotate-180 motion-reduce:transition-none"
        />
      </summary>
      <div className="border-t border-[var(--app-divider)] px-1 py-4 sm:px-2">
        {selectedItem ? (
          <form
            className="grid gap-3"
            onSubmit={async (event) => {
              event.preventDefault();
              if (mutationPending) return;
              if (!noteTitle.trim() || !noteContent.trim()) {
                pushToast(
                  'error',
                  copy.market.noteFailed,
                  copy.common.required,
                );
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
                resetNoteEditor();
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
            <fieldset
              disabled={mutationPending}
              className="contents disabled:opacity-60"
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
                <span className="text-sm font-medium">
                  {copy.market.noteTitle}
                </span>
                <input
                  name="research_note_title"
                  required
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
                  required
                  value={noteContent}
                  onChange={(event) => setNoteContent(event.target.value)}
                  placeholder={copy.market.noteContentPlaceholder}
                  rows={5}
                  className="app-field min-h-32 rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                />
              </label>
              <label className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.market.noteDate}
                </span>
                <input
                  name="research_note_date"
                  type="date"
                  value={noteDate}
                  onChange={(event) => setNoteDate(event.target.value)}
                  className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                />
              </label>
            </fieldset>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="submit"
                disabled={mutationPending}
                className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm"
              >
                {createResearchNote.isPending || updateResearchNote.isPending
                  ? copy.market.savingNote
                  : editingNoteId !== null
                    ? copy.market.updateNote
                    : copy.market.saveNote}
              </button>
              {editingNoteId !== null ? (
                <button
                  type="button"
                  onClick={() => resetNoteEditor()}
                  disabled={mutationPending}
                  className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-4 py-2 text-sm"
                >
                  {copy.market.cancelEdit}
                </button>
              ) : null}
            </div>
          </form>
        ) : (
          <div className="app-muted text-sm">{copy.market.noSelection}</div>
        )}
      </div>
    </details>
  );
}

function MarketResearchNoteHistory({
  controller,
}: {
  controller: MarketPageController;
}) {
  const {
    copy,
    activeSymbol,
    createResearchNote,
    updateResearchNote,
    resetNoteEditor,
    editingNoteId,
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
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  useEffect(() => setPendingDeleteId(null), [activeSymbol]);
  const mutationPending =
    createResearchNote.isPending ||
    updateResearchNote.isPending ||
    deleteResearchNote.isPending;
  const invalidDateRange = Boolean(
    noteFilterDateFrom &&
    noteFilterDateTo &&
    noteFilterDateFrom > noteFilterDateTo,
  );
  return (
    <div
      className="min-w-0 border-y border-[var(--app-divider)] px-1 py-4 sm:px-3 sm:py-5"
      data-testid="market-research-note-history"
    >
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
            max={noteFilterDateTo || undefined}
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
            min={noteFilterDateFrom || undefined}
            value={noteFilterDateTo}
            onChange={(event) => setNoteFilterDateTo(event.target.value)}
            className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
            aria-label={copy.market.noteDateTo}
          />
        </label>
      </FilterBar>
      {invalidDateRange ? (
        <p role="alert" className="mt-3 text-sm text-[var(--app-danger-text)]">
          {copy.market.invalidNoteDateRange}
        </p>
      ) : null}
      {notes.isLoading ? (
        <div className="app-muted mt-4 text-sm">{copy.states.loading}</div>
      ) : notes.isError ? (
        <div className="mt-4 space-y-2" role="alert">
          <p className="text-sm text-[var(--app-danger-text)]">
            {copy.market.noteFailed}: {getErrorMessage(notes.error)}
          </p>
          <button
            type="button"
            onClick={() => void notes.refetch()}
            className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-xs"
          >
            {copy.states.retry}
          </button>
        </div>
      ) : notes.data && notes.data.items.length > 0 ? (
        <div className="mt-4 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {notes.data.items.map((note) => (
            <div key={note.id} className="px-1 py-4 sm:px-2">
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
                    disabled={mutationPending}
                    onClick={() => {
                      setPendingDeleteId(null);
                      setEditingNoteId(note.id);
                      setNoteType(note.entry_kind);
                      setNotePriority(note.priority);
                      setNoteTitle(note.title);
                      setNoteContent(note.content);
                      setNoteDate(note.event_date ?? '');
                      document
                        .getElementById('market-research-note-editor')
                        ?.scrollIntoView?.({
                          behavior: window.matchMedia(
                            '(prefers-reduced-motion: reduce)',
                          ).matches
                            ? 'auto'
                            : 'smooth',
                          block: 'start',
                        });
                    }}
                  >
                    {copy.market.editNote}
                  </button>
                  {pendingDeleteId === note.id ? (
                    <>
                      <button
                        type="button"
                        disabled={mutationPending}
                        className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs text-[var(--app-danger-text)] sm:min-h-8"
                        onClick={async () => {
                          if (mutationPending) return;
                          try {
                            await deleteResearchNote.mutateAsync(note.id);
                            if (editingNoteId === note.id)
                              resetNoteEditor(activeSymbol, note.id);
                            setPendingDeleteId(null);
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
                        {deleteResearchNote.isPending
                          ? copy.market.removingNote
                          : copy.market.confirmRemove}
                      </button>
                      <button
                        type="button"
                        disabled={mutationPending}
                        className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs sm:min-h-8"
                        onClick={() => setPendingDeleteId(null)}
                      >
                        {copy.market.cancelRemove}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      disabled={mutationPending}
                      className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs sm:min-h-8"
                      onClick={() => setPendingDeleteId(note.id)}
                    >
                      {copy.market.remove}
                    </button>
                  )}
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
