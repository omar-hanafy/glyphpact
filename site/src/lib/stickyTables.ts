interface StickyTableState {
  wrapper: HTMLElement;
  table: HTMLTableElement;
  sourceHead: HTMLTableSectionElement;
  pin: HTMLDivElement;
  pinTable: HTMLTableElement;
  colgroup: HTMLTableColElement[];
  syncColumns: () => void;
}

const states: StickyTableState[] = [];
let scheduledFrame = 0;

function removeDuplicateIdentity(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>('[id]').forEach((element) => {
    element.removeAttribute('id');
  });

  root
    .querySelectorAll<HTMLElement>('a, button, input, select, textarea, [tabindex]')
    .forEach((element) => {
      element.setAttribute('tabindex', '-1');
    });
}

function createState(wrapper: HTMLElement): StickyTableState | null {
  const table = wrapper.querySelector<HTMLTableElement>(':scope > table');
  const sourceHead = table?.tHead;
  const firstRow = sourceHead?.rows[0];
  if (!table || !sourceHead || !firstRow) return null;

  const pin = document.createElement('div');
  pin.className = 'gp-table-pin';
  pin.hidden = true;
  pin.inert = true;
  pin.setAttribute('aria-hidden', 'true');

  const comparisonContext = wrapper.closest<HTMLElement>('.gp-compare');
  if (comparisonContext) {
    pin.classList.add('gp-compare');
    Array.from(comparisonContext.attributes)
      .filter((attribute) => attribute.name.startsWith('data-astro-'))
      .forEach((attribute) => pin.setAttribute(attribute.name, attribute.value));
  }

  const pinTable = table.cloneNode(false) as HTMLTableElement;
  pinTable.removeAttribute('id');
  pinTable.style.tableLayout = 'fixed';

  const colgroupElement = document.createElement('colgroup');
  const colgroup = Array.from(firstRow.cells, () => document.createElement('col'));
  colgroupElement.append(...colgroup);

  const clonedHead = sourceHead.cloneNode(true) as HTMLTableSectionElement;
  removeDuplicateIdentity(clonedHead);
  pinTable.append(colgroupElement, clonedHead);
  pin.append(pinTable);
  document.body.append(pin);

  const state: StickyTableState = {
    wrapper,
    table,
    sourceHead,
    pin,
    pinTable,
    colgroup,
    syncColumns: () => {
      const cells = Array.from(sourceHead.rows[0]?.cells ?? []);
      const tableWidth = table.getBoundingClientRect().width;

      pinTable.style.width = `${tableWidth}px`;
      pinTable.style.minWidth = `${tableWidth}px`;

      cells.forEach((cell, index) => {
        const column = colgroup[index];
        if (column) column.style.width = `${cell.getBoundingClientRect().width}px`;
      });
    },
  };

  wrapper.addEventListener('scroll', scheduleUpdate, { passive: true });

  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(() => {
      state.syncColumns();
      scheduleUpdate();
    });
    observer.observe(wrapper);
    observer.observe(table);
  }

  state.syncColumns();
  return state;
}

function updatePins(): void {
  scheduledFrame = 0;
  const navigationBottom =
    document.querySelector<HTMLElement>('.gp-header')?.getBoundingClientRect().bottom ?? 0;

  states.forEach(({ wrapper, table, sourceHead, pin, pinTable }) => {
    const wrapperRect = wrapper.getBoundingClientRect();
    const tableRect = table.getBoundingClientRect();
    const headRect = sourceHead.getBoundingClientRect();
    const active =
      headRect.top < navigationBottom &&
      wrapperRect.bottom > navigationBottom + headRect.height;

    pin.hidden = !active;
    if (!active) return;

    pin.style.insetBlockStart = `${navigationBottom}px`;
    pin.style.insetInlineStart = `${wrapperRect.left}px`;
    pin.style.width = `${wrapperRect.width}px`;
    pin.style.height = `${headRect.height}px`;
    pinTable.style.transform = `translateX(${tableRect.left - wrapperRect.left}px)`;
  });
}

function scheduleUpdate(): void {
  if (scheduledFrame) return;
  scheduledFrame = window.requestAnimationFrame(updatePins);
}

export function mountStickyTables(): void {
  document.querySelectorAll<HTMLElement>('.gp-table-wrap').forEach((wrapper) => {
    const state = createState(wrapper);
    if (state) states.push(state);
  });

  if (states.length === 0) return;

  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', () => {
    states.forEach((state) => state.syncColumns());
    scheduleUpdate();
  });

  document.fonts?.ready.then(() => {
    states.forEach((state) => state.syncColumns());
    scheduleUpdate();
  });

  updatePins();
}
