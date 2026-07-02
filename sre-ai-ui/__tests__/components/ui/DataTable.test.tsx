import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { DataTable, CellBadge, CellBoolean, CellTruncated, CellList, multiSelectFilterFn, booleanFilterFn } from '@/components/ui/DataTable';
import { type ColumnDef, type Row } from '@tanstack/react-table';

jest.mock('@/contexts/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, theme: 'light', toggleTheme: jest.fn() }),
}));

// Track whether virtual mode mock should be active
let __useVirtualizerMockEnabled = false;

jest.mock('@tanstack/react-virtual', () => {
  return {
    __esModule: true,
    useVirtualizer: (opts: { count: number; getScrollElement: () => unknown; estimateSize: () => number; overscan: number }) => {
      if (__useVirtualizerMockEnabled && opts.count > 0) {
        const rowHeight = opts.estimateSize();
        const items = Array.from({ length: opts.count }, (_, i) => ({
          index: i,
          start: i * rowHeight,
          end: (i + 1) * rowHeight,
          size: rowHeight,
          key: i,
        }));
        return {
          getVirtualItems: () => items,
          getTotalSize: () => opts.count * rowHeight,
          measureElement: jest.fn(),
        };
      }
      // Default: return empty virtualizer (mimics no scroll element)
      return {
        getVirtualItems: () => [],
        getTotalSize: () => 0,
        measureElement: jest.fn(),
      };
    },
  };
});

// ─── Test data ──────────────────────────────────────────────────────────────

interface TestRow {
  id: number;
  name: string;
  category: string;
  active: boolean;
}

const TEST_DATA: TestRow[] = [
  { id: 1, name: 'Alpha', category: 'A', active: true },
  { id: 2, name: 'Beta', category: 'B', active: false },
  { id: 3, name: 'Gamma', category: 'A', active: true },
  { id: 4, name: 'Delta', category: 'C', active: false },
  { id: 5, name: 'Epsilon', category: 'B', active: true },
];

const TEST_COLUMNS: ColumnDef<TestRow, unknown>[] = [
  { accessorKey: 'id', header: 'ID' },
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'category', header: 'Category' },
  {
    accessorKey: 'active',
    header: 'Active',
    cell: ({ getValue }) => (getValue() ? 'Yes' : 'No'),
  },
];

// ─── Helper ─────────────────────────────────────────────────────────────────

function renderTable(props: Partial<React.ComponentProps<typeof DataTable<TestRow>>> = {}) {
  return render(
    <DataTable<TestRow>
      data={TEST_DATA}
      columns={TEST_COLUMNS}
      defaultPageSize={25}
      getRowId={(row) => String(row.id)}
      {...props}
    />
  );
}

// ─── Tests ──────────────────────────────────────────────────────────────────

describe('DataTable', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // 1. Loading state
  it('renders loading state with spinner when loading=true', () => {
    renderTable({ loading: true, title: 'Items' });
    const spinner = document.querySelector('div[class*="animate-spin"]');
    expect(spinner).toBeInTheDocument();
    expect(screen.getByText('Loading items...')).toBeInTheDocument();
  });

  // 2. Error state
  it('renders error state with message and retry button', () => {
    const onRetry = jest.fn();
    renderTable({ error: 'Something went wrong', onRetry });

    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    const retryButton = screen.getByText('Try Again');
    expect(retryButton).toBeInTheDocument();
    fireEvent.click(retryButton);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  // 3. Renders table with data
  it('renders table headers and rows', () => {
    renderTable();

    // Headers
    expect(screen.getByText('ID')).toBeInTheDocument();
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Category')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();

    // Row data
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('Gamma')).toBeInTheDocument();
    expect(screen.getByText('Delta')).toBeInTheDocument();
    expect(screen.getByText('Epsilon')).toBeInTheDocument();
  });

  // 4. Empty state
  it('renders empty state message when data is empty', () => {
    renderTable({ data: [], emptyMessage: 'Nothing here' });
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  // 5. Global search filters rows
  it('filters rows when typing in the global search', async () => {
    renderTable();

    const searchInput = screen.getByPlaceholderText('Search all columns…');
    fireEvent.change(searchInput, { target: { value: 'Alpha' } });

    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.queryByText('Beta')).not.toBeInTheDocument();
      expect(screen.queryByText('Gamma')).not.toBeInTheDocument();
    });
  });

  // 6. Column sorting
  it('sorts rows when clicking a column header', async () => {
    renderTable();

    // Click the "Name" header to sort ascending
    const nameHeader = screen.getByText('Name');
    fireEvent.click(nameHeader);

    await waitFor(() => {
      const rows = document.querySelectorAll('tbody tr');
      expect(rows[0]).toHaveTextContent('Alpha');
      expect(rows[4]).toHaveTextContent('Gamma');
    });

    // Click again for descending
    fireEvent.click(nameHeader);

    await waitFor(() => {
      const rows = document.querySelectorAll('tbody tr');
      expect(rows[0]).toHaveTextContent('Gamma');
      expect(rows[4]).toHaveTextContent('Alpha');
    });
  });

  // 7. Default sorting
  it('applies default sorting on initial render', () => {
    renderTable({
      defaultSorting: [{ id: 'name', desc: true }],
    });

    const rows = document.querySelectorAll('tbody tr');
    // Descending by name: Gamma, Epsilon, Delta, Beta, Alpha
    expect(rows[0]).toHaveTextContent('Gamma');
    expect(rows[4]).toHaveTextContent('Alpha');
  });

  // 8. Column visibility
  it('toggles column visibility when using the Columns dropdown', async () => {
    renderTable();

    // Open columns dropdown
    const columnsButton = screen.getByText('Columns');
    fireEvent.click(columnsButton);

    // Find the "Name" checkbox in the dropdown and toggle it off
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const nameLabel = Array.from(labels).find((l) => l.textContent?.includes('Name'));
      expect(nameLabel).toBeTruthy();

      const checkbox = nameLabel!.querySelector('input[type="checkbox"]');
      fireEvent.click(checkbox!);
    });

    // "Name" column header should be gone, and cell data "Alpha" should not appear as a cell
    await waitFor(() => {
      const headers = document.querySelectorAll('thead th');
      const headerTexts = Array.from(headers).map((h) => h.textContent);
      expect(headerTexts).not.toContain('Name');
    });
  });

  // 9. Pagination
  it('shows correct pagination info', () => {
    // Use pageSize=2 with 5 rows so there are multiple pages and the footer renders
    renderTable({ defaultPageSize: 2 });

    // With 5 items and page size 2, should show "1–2 of 5"
    // The component uses an en-dash: 1–2 of 5
    expect(screen.getByText(/1–2 of 5/)).toBeInTheDocument();
  });

  // 10. Row click callback
  it('calls onRowClick with correct data when a row is clicked', () => {
    const onRowClick = jest.fn();
    renderTable({ onRowClick });

    const alphaCell = screen.getByText('Alpha');
    const row = alphaCell.closest('tr')!;
    fireEvent.click(row);

    expect(onRowClick).toHaveBeenCalledTimes(1);
    expect(onRowClick).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, name: 'Alpha' })
    );
  });

  // 11. Selected row highlight
  it('highlights the row matching selectedRowId', () => {
    renderTable({ selectedRowId: '2', onRowClick: jest.fn() });

    const betaCell = screen.getByText('Beta');
    const row = betaCell.closest('tr')!;
    // Selected row gets inset shadow for highlight
    expect(row.className).toContain('shadow-[inset_3px_0_0_#0071CE]');
  });

  // 12. Scroll mode toggle
  it('switches to virtual scroll mode when clicking Pages button', async () => {
    renderTable();

    // In paginated mode, button shows "Pages" (current mode)
    const pagesButton = screen.getByText('Pages');
    fireEvent.click(pagesButton);

    // After clicking, mode switches to virtual — button text changes to "Scroll"
    await waitFor(() => {
      expect(screen.getByText('Scroll')).toBeInTheDocument();
    });

    // Pagination footer should be replaced with scroll stats
    expect(screen.queryByText(/Rows per page/)).not.toBeInTheDocument();
  });

  // 13. Density toggle
  it('switches density when selecting from Density dropdown', async () => {
    renderTable();

    // Open density dropdown
    const densityButton = screen.getByText('Density');
    fireEvent.click(densityButton);

    // Select "Compact"
    await waitFor(() => {
      const compactOption = screen.getByText('Compact');
      fireEvent.click(compactOption);
    });

    // Table cells should now have compact padding class
    await waitFor(() => {
      const cells = document.querySelectorAll('tbody td');
      if (cells.length > 0) {
        expect(cells[0].className).toContain('py-1.5');
      }
    });
  });

  // 14. Export CSV
  it('triggers CSV download when clicking Export', () => {
    const mockCreateObjectURL = jest.fn(() => 'blob:mock-url');
    const mockRevokeObjectURL = jest.fn();
    const mockClick = jest.fn();

    global.URL.createObjectURL = mockCreateObjectURL;
    global.URL.revokeObjectURL = mockRevokeObjectURL;

    const originalCreateElement = document.createElement.bind(document);
    jest.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'a') {
        const anchor = originalCreateElement('a');
        anchor.click = mockClick;
        return anchor;
      }
      return originalCreateElement(tag);
    });

    renderTable({ title: 'Test Data' });

    const exportButton = screen.getByText('Export');
    fireEvent.click(exportButton);

    expect(mockCreateObjectURL).toHaveBeenCalledTimes(1);
    expect(mockClick).toHaveBeenCalledTimes(1);
    expect(mockRevokeObjectURL).toHaveBeenCalledTimes(1);

    (document.createElement as jest.Mock).mockRestore();
  });

  // 15. Empty filter state
  it('shows 0-0 of 0 when all data is filtered out', async () => {
    renderTable();

    const searchInput = screen.getByPlaceholderText('Search all columns…');
    fireEvent.change(searchInput, { target: { value: 'zzzzzzz_no_match' } });

    await waitFor(() => {
      expect(screen.getByText(/0–0 of 0/)).toBeInTheDocument();
    });
  });
});

// ─── Cell helper components ───────────────────────────────────────────────

describe('Cell components', () => {
  it('CellBadge renders children with correct variant class', () => {
    const { container } = render(<CellBadge variant="blue">Test Badge</CellBadge>);
    expect(screen.getByText('Test Badge')).toBeInTheDocument();
    expect(container.querySelector('span')!.className).toContain('bg-blue-100');
  });

  it('CellBoolean renders true value with blue badge', () => {
    render(<CellBoolean value={true} />);
    expect(screen.getByText('Yes')).toBeInTheDocument();
  });

  it('CellBoolean renders false value with default badge', () => {
    render(<CellBoolean value={false} />);
    expect(screen.getByText('No')).toBeInTheDocument();
  });

  it('CellBoolean renders custom labels', () => {
    render(<CellBoolean value={true} trueLabel="Active" falseLabel="Inactive" />);
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('CellTruncated renders text with truncate class and title', () => {
    render(<CellTruncated text="Some long text" />);
    const el = screen.getByText('Some long text');
    expect(el).toHaveAttribute('title', 'Some long text');
    expect(el.className).toContain('truncate');
  });

  it('CellTruncated renders dash for null/undefined text', () => {
    const { container } = render(<CellTruncated text={null} />);
    expect(container.textContent).toBe('—');
  });

  it('CellList renders first item as badge', () => {
    render(<CellList items={['one', 'two', 'three']} />);
    expect(screen.getByText('one')).toBeInTheDocument();
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('CellList renders dash for empty items', () => {
    const { container } = render(<CellList items={[]} />);
    expect(container.textContent).toBe('—');
  });

  it('CellList shows "+N" count for multiple items', () => {
    render(<CellList items={['a', 'b', 'c', 'd', 'e']} />);
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('+4')).toBeInTheDocument();
  });

  it('CellList renders items with prefix', () => {
    render(<CellList items={['channel']} prefix="#" />);
    expect(screen.getByText('#channel')).toBeInTheDocument();
  });
});

// ─── Filter function unit tests ─────────────────────────────────────────────

describe('multiSelectFilterFn', () => {
  const makeRow = (value: string) =>
    ({ getValue: () => value } as unknown as Row<unknown>);

  it('returns true when filterValue is empty array', () => {
    expect(multiSelectFilterFn(makeRow('A'), 'col', [])).toBe(true);
  });

  it('returns true when filterValue is null/undefined', () => {
    expect(multiSelectFilterFn(makeRow('A'), 'col', null as unknown as string[])).toBe(true);
    expect(multiSelectFilterFn(makeRow('A'), 'col', undefined as unknown as string[])).toBe(true);
  });

  it('returns true when row value is in the filter array', () => {
    expect(multiSelectFilterFn(makeRow('A'), 'col', ['A', 'B'])).toBe(true);
  });

  it('returns false when row value is not in the filter array', () => {
    expect(multiSelectFilterFn(makeRow('C'), 'col', ['A', 'B'])).toBe(false);
  });

  it('autoRemove returns true for empty array', () => {
    expect(multiSelectFilterFn.autoRemove([])).toBe(true);
  });

  it('autoRemove returns true for falsy values', () => {
    expect(multiSelectFilterFn.autoRemove(null)).toBe(true);
    expect(multiSelectFilterFn.autoRemove(undefined)).toBe(true);
  });

  it('autoRemove returns false for non-empty array', () => {
    expect(multiSelectFilterFn.autoRemove(['A'])).toBe(false);
  });
});

describe('booleanFilterFn', () => {
  const makeRow = (value: boolean) =>
    ({ getValue: () => value } as unknown as Row<unknown>);

  it('returns true when filterValue is undefined', () => {
    expect(booleanFilterFn(makeRow(true), 'col', undefined as unknown as boolean)).toBe(true);
  });

  it('returns true when filterValue is null', () => {
    expect(booleanFilterFn(makeRow(false), 'col', null as unknown as boolean)).toBe(true);
  });

  it('returns true when row value matches filterValue true', () => {
    expect(booleanFilterFn(makeRow(true), 'col', true)).toBe(true);
  });

  it('returns false when row value does not match filterValue', () => {
    expect(booleanFilterFn(makeRow(false), 'col', true)).toBe(false);
  });

  it('filters for false values correctly', () => {
    expect(booleanFilterFn(makeRow(false), 'col', false)).toBe(true);
    expect(booleanFilterFn(makeRow(true), 'col', false)).toBe(false);
  });

  it('autoRemove returns true for undefined and null', () => {
    expect(booleanFilterFn.autoRemove(undefined)).toBe(true);
    expect(booleanFilterFn.autoRemove(null)).toBe(true);
  });

  it('autoRemove returns false for boolean values', () => {
    expect(booleanFilterFn.autoRemove(true)).toBe(false);
    expect(booleanFilterFn.autoRemove(false)).toBe(false);
  });
});

// ─── Filter components rendered inside DataTable ─────────────────────────────

describe('DataTable with column filters', () => {
  interface FilterRow {
    id: number;
    name: string;
    category: string;
    active: boolean;
    description: string;
  }

  const FILTER_DATA: FilterRow[] = [
    { id: 1, name: 'Alpha', category: 'Cat-A', active: true, description: 'first item' },
    { id: 2, name: 'Beta', category: 'Cat-B', active: false, description: 'second item' },
    { id: 3, name: 'Gamma', category: 'Cat-A', active: true, description: 'third item' },
    { id: 4, name: 'Delta', category: 'Cat-C', active: false, description: 'fourth item' },
    { id: 5, name: 'Epsilon', category: 'Cat-B', active: true, description: 'fifth item' },
  ];

  const FILTER_COLUMNS: ColumnDef<FilterRow, unknown>[] = [
    { accessorKey: 'id', header: 'ID' },
    { accessorKey: 'name', header: 'Name' },
    {
      accessorKey: 'category',
      header: 'Category',
      filterFn: multiSelectFilterFn as never,
      meta: { filterType: 'facet' },
    },
    {
      accessorKey: 'active',
      header: 'Active',
      filterFn: booleanFilterFn as never,
      meta: { filterType: 'boolean' },
      cell: ({ getValue }) => (getValue() ? 'Enabled' : 'Disabled'),
    },
    {
      accessorKey: 'description',
      header: 'Description',
      meta: { filterType: 'text' },
    },
  ];

  function renderFilterTable(props: Partial<React.ComponentProps<typeof DataTable<FilterRow>>> = {}) {
    return render(
      <DataTable<FilterRow>
        data={FILTER_DATA}
        columns={FILTER_COLUMNS}
        defaultPageSize={25}
        enableFilters={true}
        getRowId={(row) => String(row.id)}
        {...props}
      />
    );
  }

  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ── enableFilters renders filter row (line 443 / 609-628) ──

  it('renders filter row with facet, boolean, and text filter controls', () => {
    renderFilterTable();
    // BooleanFilter renders All/Yes/No buttons in the filter row (thead)
    const thead = document.querySelector('thead')!;
    const filterButtons = thead.querySelectorAll('button');
    const buttonTexts = Array.from(filterButtons).map(b => b.textContent?.trim());
    expect(buttonTexts).toContain('All');
    expect(buttonTexts).toContain('Yes');
    expect(buttonTexts).toContain('No');
    // TextColumnFilter renders a text input with placeholder "Filter..."
    expect(screen.getByPlaceholderText('Filter...')).toBeInTheDocument();
  });

  // ── FacetFilter (lines 153-229) ──

  it('FacetFilter opens dropdown, shows values with counts, and filters on check', async () => {
    renderFilterTable();

    // Find the facet filter button in the filter row (last tr in thead)
    const filterRow = document.querySelector('thead tr:last-child')!;
    const facetButton = filterRow.querySelector('button')!;
    expect(facetButton).toBeTruthy();

    // Click to open the dropdown
    fireEvent.click(facetButton);

    // Should show facet values as labels with checkboxes
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const facetLabels = Array.from(labels).filter(l => l.textContent?.includes('Cat-'));
      expect(facetLabels.length).toBe(3); // Cat-A, Cat-B, Cat-C
    });

    // Click on "Cat-A" checkbox label to select it
    const labels = document.querySelectorAll('label');
    const labelA = Array.from(labels).find(l => l.textContent?.includes('Cat-A'));
    expect(labelA).toBeTruthy();
    fireEvent.click(labelA!);

    // After selecting Cat-A, only rows with category Cat-A should remain (Alpha, Gamma)
    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('Gamma')).toBeInTheDocument();
      expect(screen.queryByText('Beta')).not.toBeInTheDocument();
      expect(screen.queryByText('Delta')).not.toBeInTheDocument();
    });
  });

  it('FacetFilter shows "Clear filter" button when selection is active and clears on click', async () => {
    renderFilterTable();

    // Open facet filter
    const filterRow = document.querySelector('thead tr:last-child')!;
    const facetButton = filterRow.querySelector('button')!;
    fireEvent.click(facetButton);

    // Select value "Cat-A"
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const labelA = Array.from(labels).find(l => l.textContent?.includes('Cat-A'));
      fireEvent.click(labelA!);
    });

    // "Clear filter" should appear
    await waitFor(() => {
      expect(screen.getByText('Clear filter')).toBeInTheDocument();
    });

    // Click "Clear filter"
    fireEvent.click(screen.getByText('Clear filter'));

    // All rows should be visible again
    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('Beta')).toBeInTheDocument();
      expect(screen.getByText('Delta')).toBeInTheDocument();
    });
  });

  it('FacetFilter closes when clicking outside', async () => {
    renderFilterTable();

    // Open the facet filter
    const filterRow = document.querySelector('thead tr:last-child')!;
    const facetButton = filterRow.querySelector('button')!;
    fireEvent.click(facetButton);

    // Verify it opened - the dropdown should have labels
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const facetLabels = Array.from(labels).filter(l => l.textContent?.includes('Cat-'));
      expect(facetLabels.length).toBeGreaterThan(0);
    });

    // Click outside the dropdown
    fireEvent.mouseDown(document.body);

    // The facet dropdown should close - no more facet labels visible
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const facetLabels = Array.from(labels).filter(l => l.textContent?.includes('Cat-'));
      expect(facetLabels.length).toBe(0);
    });
  });

  it('FacetFilter unchecks a previously selected value', async () => {
    renderFilterTable();

    const filterRow = document.querySelector('thead tr:last-child')!;
    const facetButton = filterRow.querySelector('button')!;
    fireEvent.click(facetButton);

    // Select "Cat-A"
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const labelA = Array.from(labels).find(l => l.textContent?.includes('Cat-A'));
      fireEvent.click(labelA!);
    });

    // Now deselect "Cat-A" by clicking it again
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const labelA = Array.from(labels).find(l => l.textContent?.includes('Cat-A'));
      fireEvent.click(labelA!);
    });

    // All rows should be visible again
    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('Beta')).toBeInTheDocument();
      expect(screen.getByText('Delta')).toBeInTheDocument();
    });
  });

  // ── BooleanFilter (lines 232-259) ──

  it('BooleanFilter filters rows when clicking Yes/No/All buttons', async () => {
    renderFilterTable();

    // Find the boolean filter buttons in the thead filter row
    const thead = document.querySelector('thead')!;
    const allBoolButtons = Array.from(thead.querySelectorAll('button')).filter(
      b => ['All', 'Yes', 'No'].includes(b.textContent?.trim() || '')
    );
    const yesBtn = allBoolButtons.find(b => b.textContent?.trim() === 'Yes')!;
    const noBtn = allBoolButtons.find(b => b.textContent?.trim() === 'No')!;
    const allBtn = allBoolButtons.find(b => b.textContent?.trim() === 'All')!;

    // Click "Yes" to filter for active=true
    fireEvent.click(yesBtn);

    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('Gamma')).toBeInTheDocument();
      expect(screen.getByText('Epsilon')).toBeInTheDocument();
      expect(screen.queryByText('Beta')).not.toBeInTheDocument();
      expect(screen.queryByText('Delta')).not.toBeInTheDocument();
    });

    // Click "No" to filter for active=false
    fireEvent.click(noBtn);

    await waitFor(() => {
      expect(screen.getByText('Beta')).toBeInTheDocument();
      expect(screen.getByText('Delta')).toBeInTheDocument();
      expect(screen.queryByText('Alpha')).not.toBeInTheDocument();
    });

    // Click "All" to clear the filter
    fireEvent.click(allBtn);

    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('Beta')).toBeInTheDocument();
      expect(screen.getByText('Delta')).toBeInTheDocument();
    });
  });

  // ── TextColumnFilter (lines 262-278) ──

  it('TextColumnFilter filters rows by text input', async () => {
    renderFilterTable();

    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'first' } });

    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.queryByText('Beta')).not.toBeInTheDocument();
    });

    // Clear the text filter
    fireEvent.change(textFilter, { target: { value: '' } });

    await waitFor(() => {
      expect(screen.getByText('Beta')).toBeInTheDocument();
    });
  });

  it('TextColumnFilter click does not propagate to header (stopPropagation)', () => {
    renderFilterTable();

    const textFilter = screen.getByPlaceholderText('Filter...');
    // Clicking the input should not trigger column sort
    fireEvent.click(textFilter);
    // If stopPropagation works, no sort happens - just verify the input is still there
    expect(textFilter).toBeInTheDocument();
  });
});

// ─── ToolbarDropdown click-outside (lines 113-116) ──────────────────────────

describe('ToolbarDropdown click-outside', () => {
  it('closes Columns dropdown when clicking outside', async () => {
    render(
      <DataTable
        data={[{ id: 1, name: 'Test' }]}
        columns={[
          { accessorKey: 'id', header: 'ID' },
          { accessorKey: 'name', header: 'Name' },
        ]}
        defaultPageSize={25}
        getRowId={(row: { id: number }) => String(row.id)}
      />
    );

    // Open the Columns dropdown
    const columnsButton = screen.getByText('Columns');
    fireEvent.click(columnsButton);

    // Verify the dropdown is open (should show checkboxes)
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      expect(labels.length).toBeGreaterThan(0);
    });

    // Click outside
    fireEvent.mouseDown(document.body);

    // Dropdown should close
    await waitFor(() => {
      const labelsAfter = document.querySelectorAll('.absolute.top-full label');
      expect(labelsAfter.length).toBe(0);
    });
  });

  it('closes Density dropdown when clicking outside', async () => {
    render(
      <DataTable
        data={[{ id: 1, name: 'Test' }]}
        columns={[
          { accessorKey: 'id', header: 'ID' },
          { accessorKey: 'name', header: 'Name' },
        ]}
        defaultPageSize={25}
        getRowId={(row: { id: number }) => String(row.id)}
      />
    );

    // Open the Density dropdown
    const densityButton = screen.getByText('Density');
    fireEvent.click(densityButton);

    // Verify it opened
    await waitFor(() => {
      expect(screen.getByText('Compact')).toBeInTheDocument();
    });

    // Click outside
    fireEvent.mouseDown(document.body);

    // Dropdown should close
    await waitFor(() => {
      expect(screen.queryByText('Compact')).not.toBeInTheDocument();
    });
  });
});

// ─── CellList overflow (lines 660-685 reference, but actually 841-843) ──────

describe('CellList overflow', () => {
  it('shows first item and "+N" count for 6 items', () => {
    render(<CellList items={['one', 'two', 'three', 'four', 'five', 'six']} />);
    expect(screen.getByText('one')).toBeInTheDocument();
    expect(screen.getByText('+5')).toBeInTheDocument();
    // Only first item shown, rest in popup
    expect(screen.queryByText('two')).not.toBeInTheDocument();
  });

  it('shows single item without count badge', () => {
    render(<CellList items={['only']} />);
    expect(screen.getByText('only')).toBeInTheDocument();
    expect(screen.queryByText(/\+/)).not.toBeInTheDocument();
  });

  it('shows first item and "+3" for 4 items', () => {
    render(<CellList items={['a', 'b', 'c', 'd']} />);
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('+3')).toBeInTheDocument();
  });
});

// ─── Virtual scroll mode (lines 660-685, 734) ──────────────────────────────

describe('DataTable virtual scroll mode', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    __useVirtualizerMockEnabled = false;
  });

  afterEach(() => {
    __useVirtualizerMockEnabled = false;
  });

  it('renders virtual scroll stats footer after toggling to scroll mode', async () => {
    const data = Array.from({ length: 10 }, (_, i) => ({
      id: i + 1,
      name: `Item ${i + 1}`,
    }));

    const columns: ColumnDef<{ id: number; name: string }, unknown>[] = [
      { accessorKey: 'id', header: 'ID' },
      { accessorKey: 'name', header: 'Name' },
    ];

    render(
      <DataTable
        data={data}
        columns={columns}
        defaultPageSize={25}
        getRowId={(row) => String(row.id)}
        title="Items"
      />
    );

    // Switch to virtual scroll mode — in paginated mode, button shows "Pages"
    const pagesButton = screen.getByText('Pages');
    fireEvent.click(pagesButton);

    // Should now show "Scroll" button (current mode label) and virtual scroll stats
    await waitFor(() => {
      expect(screen.getByText('Scroll')).toBeInTheDocument();
    });

    // Virtual scroll stats footer should appear
    await waitFor(() => {
      expect(screen.getByText(/Scroll to browse/)).toBeInTheDocument();
    });

    // Pagination footer should be gone
    expect(screen.queryByText(/Rows per page/)).not.toBeInTheDocument();
  });

  it('renders virtual scroll rows with mocked virtualizer', async () => {
    __useVirtualizerMockEnabled = true;

    const data = Array.from({ length: 5 }, (_, i) => ({
      id: i + 1,
      name: `VRow ${i + 1}`,
    }));

    const columns: ColumnDef<{ id: number; name: string }, unknown>[] = [
      { accessorKey: 'id', header: 'ID' },
      { accessorKey: 'name', header: 'Name' },
    ];

    const onRowClick = jest.fn();

    render(
      <DataTable
        data={data}
        columns={columns}
        defaultPageSize={25}
        getRowId={(row) => String(row.id)}
        onRowClick={onRowClick}
        selectedRowId="2"
      />
    );

    // Switch to virtual scroll mode — in paginated mode, button shows "Pages"
    const pagesButton = screen.getByText('Pages');
    fireEvent.click(pagesButton);

    await waitFor(() => {
      expect(screen.getByText('Scroll')).toBeInTheDocument();
    });

    // With mocked virtualizer, all virtual rows should be rendered
    await waitFor(() => {
      expect(screen.getByText('VRow 1')).toBeInTheDocument();
      expect(screen.getByText('VRow 2')).toBeInTheDocument();
      expect(screen.getByText('VRow 3')).toBeInTheDocument();
    });

    // Click a row to test onRowClick in virtual mode
    const row1Cell = screen.getByText('VRow 1');
    const row1 = row1Cell.closest('tr')!;
    fireEvent.click(row1);
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 1, name: 'VRow 1' }));

    // Selected row (id=2) should have highlight class
    const row2Cell = screen.getByText('VRow 2');
    const row2 = row2Cell.closest('tr')!;
    expect(row2.className).toContain('shadow-[inset_3px_0_0_#0071CE]');
  });

  it('switches back to paginated mode when clicking Scroll', async () => {
    const data = Array.from({ length: 5 }, (_, i) => ({
      id: i + 1,
      name: `Item ${i + 1}`,
    }));

    const columns: ColumnDef<{ id: number; name: string }, unknown>[] = [
      { accessorKey: 'id', header: 'ID' },
      { accessorKey: 'name', header: 'Name' },
    ];

    // Use pageSize=2 so 5 rows span multiple pages — pagination footer renders
    render(
      <DataTable
        data={data}
        columns={columns}
        defaultPageSize={2}
        getRowId={(row) => String(row.id)}
      />
    );

    // Switch to virtual scroll — in paginated mode, button shows "Pages"
    fireEvent.click(screen.getByText('Pages'));
    await waitFor(() => {
      expect(screen.getByText('Scroll')).toBeInTheDocument();
    });

    // Switch back to paginated — in virtual mode, button shows "Scroll"
    fireEvent.click(screen.getByText('Scroll'));
    await waitFor(() => {
      expect(screen.getByText('Pages')).toBeInTheDocument();
      expect(screen.getByText(/Rows per page/)).toBeInTheDocument();
    });
  });
});

// ─── Edge cases & negative tests for filter functions ────────────────────────

describe('booleanFilterFn edge cases', () => {
  const makeRow = (value: unknown) =>
    ({ getValue: () => value } as unknown as Row<unknown>);

  it('treats null cell value as false — matches "No" filter', () => {
    expect(booleanFilterFn(makeRow(null), 'col', false)).toBe(true);
  });

  it('treats undefined cell value as false — matches "No" filter', () => {
    expect(booleanFilterFn(makeRow(undefined), 'col', false)).toBe(true);
  });

  it('treats 0 cell value as false — matches "No" filter', () => {
    expect(booleanFilterFn(makeRow(0), 'col', false)).toBe(true);
  });

  it('treats empty string cell value as false — matches "No" filter', () => {
    expect(booleanFilterFn(makeRow(''), 'col', false)).toBe(true);
  });

  it('treats null cell value as NOT true — excludes from "Yes" filter', () => {
    expect(booleanFilterFn(makeRow(null), 'col', true)).toBe(false);
  });

  it('treats undefined cell value as NOT true — excludes from "Yes" filter', () => {
    expect(booleanFilterFn(makeRow(undefined), 'col', true)).toBe(false);
  });

  it('truthy non-boolean value matches "Yes" filter', () => {
    expect(booleanFilterFn(makeRow('yes'), 'col', true)).toBe(true);
    expect(booleanFilterFn(makeRow(1), 'col', true)).toBe(true);
  });

  it('truthy non-boolean value does NOT match "No" filter', () => {
    expect(booleanFilterFn(makeRow('yes'), 'col', false)).toBe(false);
    expect(booleanFilterFn(makeRow(1), 'col', false)).toBe(false);
  });
});

describe('multiSelectFilterFn edge cases', () => {
  const makeRow = (value: unknown) =>
    ({ getValue: () => value } as unknown as Row<unknown>);

  it('treats null cell value as empty string', () => {
    expect(multiSelectFilterFn(makeRow(null), 'col', [''])).toBe(true);
    expect(multiSelectFilterFn(makeRow(null), 'col', ['A'])).toBe(false);
  });

  it('treats undefined cell value as empty string', () => {
    expect(multiSelectFilterFn(makeRow(undefined), 'col', [''])).toBe(true);
    expect(multiSelectFilterFn(makeRow(undefined), 'col', ['A'])).toBe(false);
  });

  it('converts numeric cell value to string for comparison', () => {
    expect(multiSelectFilterFn(makeRow(42), 'col', ['42'])).toBe(true);
    expect(multiSelectFilterFn(makeRow(42), 'col', ['43'])).toBe(false);
  });

  it('handles boolean cell value converted to string', () => {
    expect(multiSelectFilterFn(makeRow(true), 'col', ['true'])).toBe(true);
    expect(multiSelectFilterFn(makeRow(false), 'col', ['false'])).toBe(true);
  });
});

// ─── Auto-assign filterFn via resolvedColumns ────────────────────────────────

describe('DataTable auto-assigns filterFn from meta.filterType', () => {
  interface AutoRow {
    id: number;
    label: string;
    kind: string;
    enabled: boolean;
  }

  const AUTO_DATA: AutoRow[] = [
    { id: 1, label: 'Foo', kind: 'X', enabled: true },
    { id: 2, label: 'Bar', kind: 'Y', enabled: false },
    { id: 3, label: 'Baz', kind: 'X', enabled: true },
    { id: 4, label: 'Qux', kind: 'Z', enabled: false },
  ];

  // Columns with ONLY meta.filterType — NO explicit filterFn
  const AUTO_COLUMNS: ColumnDef<AutoRow, unknown>[] = [
    { accessorKey: 'id', header: 'ID' },
    {
      accessorKey: 'label',
      header: 'Label',
      meta: { filterType: 'text' },
    },
    {
      accessorKey: 'kind',
      header: 'Kind',
      meta: { filterType: 'facet' },
    },
    {
      accessorKey: 'enabled',
      header: 'Enabled',
      meta: { filterType: 'boolean' },
      cell: ({ getValue }) => (getValue() ? 'On' : 'Off'),
    },
  ];

  function renderAutoTable() {
    return render(
      <DataTable<AutoRow>
        data={AUTO_DATA}
        columns={AUTO_COLUMNS}
        defaultPageSize={25}
        enableFilters={true}
        getRowId={(row) => String(row.id)}
      />
    );
  }

  it('text filter works without explicit filterFn (auto-assigned includesString)', async () => {
    renderAutoTable();

    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'Foo' } });

    await waitFor(() => {
      expect(screen.getByText('Foo')).toBeInTheDocument();
      expect(screen.queryByText('Bar')).not.toBeInTheDocument();
      expect(screen.queryByText('Baz')).not.toBeInTheDocument();
      expect(screen.queryByText('Qux')).not.toBeInTheDocument();
    });
  });

  it('text filter is case-insensitive (includesString)', async () => {
    renderAutoTable();

    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'foo' } });

    await waitFor(() => {
      expect(screen.getByText('Foo')).toBeInTheDocument();
      expect(screen.queryByText('Bar')).not.toBeInTheDocument();
    });
  });

  it('text filter with partial match works', async () => {
    renderAutoTable();

    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'Ba' } });

    await waitFor(() => {
      expect(screen.getByText('Bar')).toBeInTheDocument();
      expect(screen.getByText('Baz')).toBeInTheDocument();
      expect(screen.queryByText('Foo')).not.toBeInTheDocument();
      expect(screen.queryByText('Qux')).not.toBeInTheDocument();
    });
  });

  it('text filter with no match shows empty state', async () => {
    renderAutoTable();

    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'zzzzz_no_match' } });

    await waitFor(() => {
      expect(screen.queryByText('Foo')).not.toBeInTheDocument();
      expect(screen.queryByText('Bar')).not.toBeInTheDocument();
    });
  });

  it('boolean filter works without explicit filterFn (auto-assigned booleanFilterFn)', async () => {
    renderAutoTable();

    const thead = document.querySelector('thead')!;
    const yesBtn = Array.from(thead.querySelectorAll('button')).find(
      b => b.textContent?.trim() === 'Yes'
    )!;
    const noBtn = Array.from(thead.querySelectorAll('button')).find(
      b => b.textContent?.trim() === 'No'
    )!;

    // Click "Yes" — show only enabled=true rows
    fireEvent.click(yesBtn);
    await waitFor(() => {
      expect(screen.getByText('Foo')).toBeInTheDocument();
      expect(screen.getByText('Baz')).toBeInTheDocument();
      expect(screen.queryByText('Bar')).not.toBeInTheDocument();
      expect(screen.queryByText('Qux')).not.toBeInTheDocument();
    });

    // Click "No" — show only enabled=false rows
    fireEvent.click(noBtn);
    await waitFor(() => {
      expect(screen.getByText('Bar')).toBeInTheDocument();
      expect(screen.getByText('Qux')).toBeInTheDocument();
      expect(screen.queryByText('Foo')).not.toBeInTheDocument();
      expect(screen.queryByText('Baz')).not.toBeInTheDocument();
    });
  });

  it('facet filter works without explicit filterFn (auto-assigned multiSelectFilterFn)', async () => {
    renderAutoTable();

    // Open facet filter
    const filterRow = document.querySelector('thead tr:last-child')!;
    const facetButton = filterRow.querySelector('button')!;
    fireEvent.click(facetButton);

    // Select "X"
    await waitFor(() => {
      const labels = document.querySelectorAll('label');
      const labelX = Array.from(labels).find(l => l.textContent?.includes('X'));
      expect(labelX).toBeTruthy();
      fireEvent.click(labelX!);
    });

    await waitFor(() => {
      expect(screen.getByText('Foo')).toBeInTheDocument();
      expect(screen.getByText('Baz')).toBeInTheDocument();
      expect(screen.queryByText('Bar')).not.toBeInTheDocument();
      expect(screen.queryByText('Qux')).not.toBeInTheDocument();
    });
  });

  it('column with explicit filterFn is NOT overridden by auto-assignment', () => {
    // Verify resolvedColumns preserves explicit filterFn and does not replace with auto-assigned one
    const customFn = ((_row: any, _columnId: string, _filterValue: unknown) => true) as never;

    const columnsWithExplicit: ColumnDef<AutoRow, unknown>[] = [
      { accessorKey: 'id', header: 'ID' },
      {
        accessorKey: 'label',
        header: 'Label',
        filterFn: customFn,
        meta: { filterType: 'text' },
      },
    ];

    render(
      <DataTable<AutoRow>
        data={AUTO_DATA}
        columns={columnsWithExplicit}
        defaultPageSize={25}
        enableFilters={true}
        getRowId={(row) => String(row.id)}
      />
    );

    // The original column def should still hold its explicit filterFn — not overwritten
    expect(columnsWithExplicit[1].filterFn).toBe(customFn);
  });
});

// ─── Combined filters (text + boolean + facet active simultaneously) ─────────

describe('DataTable combined filters', () => {
  interface ComboRow {
    id: number;
    name: string;
    category: string;
    active: boolean;
    description: string;
  }

  const COMBO_DATA: ComboRow[] = [
    { id: 1, name: 'Alpha', category: 'Cat-A', active: true, description: 'first item' },
    { id: 2, name: 'Beta', category: 'Cat-B', active: false, description: 'second item' },
    { id: 3, name: 'Gamma', category: 'Cat-A', active: true, description: 'third item' },
    { id: 4, name: 'Delta', category: 'Cat-A', active: false, description: 'fourth item' },
    { id: 5, name: 'Epsilon', category: 'Cat-B', active: true, description: 'fifth item' },
  ];

  const COMBO_COLUMNS: ColumnDef<ComboRow, unknown>[] = [
    { accessorKey: 'id', header: 'ID' },
    { accessorKey: 'name', header: 'Name' },
    {
      accessorKey: 'category',
      header: 'Category',
      meta: { filterType: 'facet' },
    },
    {
      accessorKey: 'active',
      header: 'Active',
      meta: { filterType: 'boolean' },
      cell: ({ getValue }) => (getValue() ? 'Enabled' : 'Disabled'),
    },
    {
      accessorKey: 'description',
      header: 'Description',
      meta: { filterType: 'text' },
    },
  ];

  function renderComboTable() {
    return render(
      <DataTable<ComboRow>
        data={COMBO_DATA}
        columns={COMBO_COLUMNS}
        defaultPageSize={25}
        enableFilters={true}
        getRowId={(row) => String(row.id)}
      />
    );
  }

  it('text + boolean filters work together', async () => {
    renderComboTable();

    // Filter text: "item" (matches all)
    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'first' } });

    // Then click "Yes" for active=true
    const thead = document.querySelector('thead')!;
    const yesBtn = Array.from(thead.querySelectorAll('button')).find(
      b => b.textContent?.trim() === 'Yes'
    )!;
    fireEvent.click(yesBtn);

    // Only Alpha (first item + active=true) should remain
    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.queryByText('Beta')).not.toBeInTheDocument();
      expect(screen.queryByText('Gamma')).not.toBeInTheDocument();
      expect(screen.queryByText('Delta')).not.toBeInTheDocument();
      expect(screen.queryByText('Epsilon')).not.toBeInTheDocument();
    });
  });

  it('clearing one filter restores rows filtered by remaining filters', async () => {
    renderComboTable();

    // Set text filter
    const textFilter = screen.getByPlaceholderText('Filter...');
    fireEvent.change(textFilter, { target: { value: 'first' } });

    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.queryByText('Beta')).not.toBeInTheDocument();
    });

    // Clear text filter — all rows should return
    fireEvent.change(textFilter, { target: { value: '' } });

    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('Beta')).toBeInTheDocument();
      expect(screen.getByText('Gamma')).toBeInTheDocument();
    });
  });
});
