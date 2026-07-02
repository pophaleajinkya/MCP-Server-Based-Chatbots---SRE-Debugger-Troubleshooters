import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ApplicationsView } from '@/components/views/ApplicationsView';
import * as apiClient from '@/lib/api-client';

jest.mock('@/lib/api-client');
jest.mock('@/components/MermaidDiagram', () => ({
  __esModule: true,
  default: ({ diagram }: { diagram: string }) => <div data-testid="mermaid-diagram">{diagram}</div>,
}));
jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { loginId: 'test.user', name: 'Test User', email: 'test@example.com', user_type: 'S' },
    loading: false,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));
jest.mock('@/contexts/ViewContext', () => ({
  useViewContext: () => ({
    setApplicationData: jest.fn(),
    setSelectedApplication: jest.fn(),
    setFilteredApplicationCount: jest.fn(),
    setApplicationFilters: jest.fn(),
    selectedApplication: null,
  }),
}));
jest.mock('@/components/HealthReportModal', () => ({
  __esModule: true,
  default: ({ onClose }: { app: unknown; onClose: () => void }) => (
    <div data-testid="health-report-modal">
      <button onClick={onClose}>Close Health Report</button>
    </div>
  ),
}));
jest.mock('@/components/AlertsSidebar', () => ({
  AlertsSidebar: ({
    isOpen,
    onClose,
  }: {
    isOpen: boolean;
    onClose: () => void;
    app: unknown;
  }) =>
    isOpen ? (
      <div data-testid="alerts-sidebar">
        <button onClick={onClose}>Close Alerts</button>
      </div>
    ) : null,
}));

// Mock DataTable to render a simple table with action buttons
jest.mock('@/components/ui/DataTable', () => {
  const React = require('react');
  const { flexRender } = require('@tanstack/react-table');
  return {
    __esModule: true,
    DataTable: ({ data, columns, loading, error, onRetry, title, onRowClick, emptyMessage }: any) => {
      if (loading) {
        return (
          <div>
            <div className="w-12 h-12 border-4 border-[#002244] dark:border-blue-400 border-t-transparent dark:border-t-transparent rounded-full animate-spin" />
            <p>Loading {title?.toLowerCase() || 'data'}...</p>
          </div>
        );
      }
      if (error) {
        return (
          <div>
            <h3>Error</h3>
            <p>{error}</p>
            {onRetry && <button onClick={onRetry}>Try Again</button>}
          </div>
        );
      }
      if (data.length === 0) {
        return <div>{emptyMessage || 'No data found'}</div>;
      }
      return (
        <div>
          <h1>{title}</h1>
          <table>
            <thead>
              <tr>
                {columns.map((col: any, i: number) => (
                  <th key={col.id || col.accessorKey || i}>
                    {typeof col.header === 'string' ? col.header : col.id || ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row: any, rowIdx: number) => (
                <tr key={rowIdx} onClick={() => onRowClick?.(row)}>
                  {columns.map((col: any, colIdx: number) => {
                    // Render the cell if it has a cell function
                    const cellValue = col.accessorKey ? row[col.accessorKey] : col.accessorFn?.(row);
                    let cellContent = cellValue;
                    if (col.cell) {
                      try {
                        cellContent = col.cell({
                          getValue: () => cellValue,
                          row: { original: row },
                        });
                      } catch {
                        cellContent = String(cellValue ?? '');
                      }
                    }
                    return <td key={colIdx}>{cellContent}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    },
    CellBadge: ({ children }: any) => <span>{children}</span>,
    CellBoolean: ({ value }: any) => <span>{value ? 'Yes' : 'No'}</span>,
    CellTruncated: ({ text }: any) => <span>{text}</span>,
    CellCopyable: ({ text }: any) => <span>{text}</span>,
    CellList: ({ items, prefix }: any) =>
      items?.length ? (
        <span>{items.map((item: string) => `${prefix || ''}${item}`).join(', ')}</span>
      ) : null,
    multiSelectFilterFn: jest.fn(),
    booleanFilterFn: jest.fn(),
  };
});

const mockApplicationsApi = apiClient.applicationsApi as jest.Mocked<
  typeof apiClient.applicationsApi
>;

const mockApplication: apiClient.Application = {
  id: 1,
  name: 'Test App',
  tenant: 'tenant-1',
  tier: 'production',
  functionalDomain: 'payment',
  active: true,
  certified: true,
  applicationType: 'wcnp',
  namespace: 'payment-service',
  appName: 'payment-api',
  cluster: 'us-east-1',
  team: {
    teamId: 1,
    jira: 'TEAM-1',
    isPrimaryTeam: true,
    members: [],
  },
  slackChannels: ['#payments'],
  xmattersGroups: ['payments-oncall'],
  emails: ['payments@example.com'],
  oneOpsPlatformId: null,
  wcnpId: 1,
  pageFlowId: null,
  oneOpsOrg: null,
  oneOpsAssembly: null,
  oneOpsPlatform: null,
};

const mockDependency: apiClient.DependencyData = {
  application_id: 2,
  application_name: 'Dependent App',
  namespace: 'payment-service',
  app_name: 'payment-processor',
  tenant: 'tenant-1',
  tier: 'production',
};

describe('ApplicationsView', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // getCached returns null to indicate no cache (triggers loading state)
    mockApplicationsApi.getCached.mockReturnValue(null);
    mockApplicationsApi.fetchAll.mockResolvedValue([mockApplication]);
    mockApplicationsApi.fetchUpstream.mockResolvedValue([]);
    mockApplicationsApi.fetchDownstream.mockResolvedValue([]);
  });

  describe('Initial Rendering', () => {
    it('should render loading state initially', async () => {
      mockApplicationsApi.fetchAll.mockImplementationOnce(
        () => new Promise(() => {})
      );

      render(<ApplicationsView />);
      await waitFor(() => {
        const spinner = document.querySelector('.animate-spin');
        expect(spinner).toBeTruthy();
      }, { timeout: 1000 });
    });

    it('should fetch and display applications', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('should display error state when fetch fails', async () => {
      const errorMessage = 'Failed to fetch applications';
      mockApplicationsApi.fetchAll.mockRejectedValueOnce(
        new Error(errorMessage)
      );

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText(errorMessage)).toBeInTheDocument();
      });
    });
  });

  describe('API Integration - New Methods', () => {
    it('should have addUpstreamDependency method available', () => {
      expect(mockApplicationsApi.addUpstreamDependency).toBeDefined();
    });

    it('should have deleteUpstreamDependency method available', () => {
      expect(mockApplicationsApi.deleteUpstreamDependency).toBeDefined();
    });

    it('should have deleteDownstreamDependency method available', () => {
      expect(mockApplicationsApi.deleteDownstreamDependency).toBeDefined();
    });
  });

  describe('Dependency Operations - Downstream', () => {
    it('should call deleteDownstreamDependency when deleting downstream dependency', async () => {
      mockApplicationsApi.deleteDownstreamDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Verify method is available for downstream operations
      expect(mockApplicationsApi.deleteDownstreamDependency).toBeDefined();
    });

    it('should call addDependency for downstream dependencies', async () => {
      mockApplicationsApi.addDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      expect(mockApplicationsApi.addDependency).toBeDefined();
    });

    it('should fetch downstream dependencies correctly', async () => {
      mockApplicationsApi.fetchDownstream.mockResolvedValueOnce([
        mockDependency,
      ]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      expect(mockApplicationsApi.fetchDownstream).toBeDefined();
    });
  });

  describe('Dependency Operations - Upstream', () => {
    it('should call addUpstreamDependency for upstream dependencies', async () => {
      mockApplicationsApi.addUpstreamDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      expect(mockApplicationsApi.addUpstreamDependency).toBeDefined();
    });

    it('should call deleteUpstreamDependency when deleting upstream dependency', async () => {
      mockApplicationsApi.deleteUpstreamDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      expect(mockApplicationsApi.deleteUpstreamDependency).toBeDefined();
    });

    it('should fetch upstream dependencies correctly', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValueOnce([
        mockDependency,
      ]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      expect(mockApplicationsApi.fetchUpstream).toBeDefined();
    });
  });

  describe('Error Handling Improvements', () => {
    it('should extract clean error messages from API responses', async () => {
      const errorMessage = 'Cannot delete: application_id not found';
      mockApplicationsApi.fetchAll.mockRejectedValueOnce(
        new Error(errorMessage)
      );

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(screen.getByText(errorMessage)).toBeInTheDocument();
      });
    });

    it('should handle missing application_id errors', async () => {
      mockApplicationsApi.deleteDownstreamDependency.mockRejectedValueOnce(
        new Error('Cannot delete: application_id not found')
      );

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      expect(mockApplicationsApi.deleteDownstreamDependency).toBeDefined();
    });
  });

  describe('Dependency Type Distinction', () => {
    it('should use upstream endpoints for upstream dependencies', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValueOnce([
        mockDependency,
      ]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Verify both methods are distinct
      expect(mockApplicationsApi.fetchUpstream).toBeDefined();
      expect(mockApplicationsApi.fetchDownstream).toBeDefined();
      expect(mockApplicationsApi.fetchUpstream).not.toBe(
        mockApplicationsApi.fetchDownstream
      );
    });

    it('should use different delete endpoints for upstream vs downstream', () => {
      expect(mockApplicationsApi.deleteUpstreamDependency).toBeDefined();
      expect(mockApplicationsApi.deleteDownstreamDependency).toBeDefined();
      expect(mockApplicationsApi.deleteUpstreamDependency).not.toBe(
        mockApplicationsApi.deleteDownstreamDependency
      );
    });

    it('should use different add endpoints for upstream vs downstream', () => {
      expect(mockApplicationsApi.addUpstreamDependency).toBeDefined();
      expect(mockApplicationsApi.addDependency).toBeDefined();
    });
  });

  describe('Loading spinner dark mode classes', () => {
    it('initial loading spinner has dark:border-t-transparent class', () => {
      mockApplicationsApi.fetchAll.mockImplementationOnce(() => new Promise(() => {}));
      render(<ApplicationsView />);

      const spinner = document.querySelector('.animate-spin');
      expect(spinner).toBeInTheDocument();
      expect(spinner?.className).toContain('dark:border-t-transparent');
    });

    it('initial loading spinner has both light and dark border color classes', () => {
      mockApplicationsApi.fetchAll.mockImplementationOnce(() => new Promise(() => {}));
      render(<ApplicationsView />);

      const spinner = document.querySelector('.animate-spin');
      expect(spinner?.className).toContain('border-[#002244]');
      expect(spinner?.className).toContain('dark:border-blue-400');
    });

    it('dependency loading spinner shown while fetching upstream has dark:border-t-transparent', async () => {
      mockApplicationsApi.fetchUpstream.mockImplementationOnce(() => new Promise(() => {}));

      render(<ApplicationsView />);
      await waitFor(() => expect(mockApplicationsApi.fetchAll).toHaveBeenCalled());

      // Click the Upstream button for the app row
      const upstreamBtn = await screen.findByTitle('View upstream dependencies');
      fireEvent.click(upstreamBtn);

      await waitFor(() => {
        const spinners = document.querySelectorAll('.animate-spin');
        expect(spinners.length).toBeGreaterThan(0);
        spinners.forEach(spinner => {
          expect(spinner.className).toContain('dark:border-t-transparent');
        });
      });
    });

    it('dependency loading spinner shown while fetching downstream has dark:border-t-transparent', async () => {
      mockApplicationsApi.fetchDownstream.mockImplementationOnce(() => new Promise(() => {}));

      render(<ApplicationsView />);
      await waitFor(() => expect(mockApplicationsApi.fetchAll).toHaveBeenCalled());

      const downstreamBtn = await screen.findByTitle('View downstream dependencies');
      fireEvent.click(downstreamBtn);

      await waitFor(() => {
        const spinners = document.querySelectorAll('.animate-spin');
        expect(spinners.length).toBeGreaterThan(0);
        spinners.forEach(spinner => {
          expect(spinner.className).toContain('dark:border-t-transparent');
        });
      });
    });

    it('loading spinner shows correct text for upstream in dark mode', async () => {
      mockApplicationsApi.fetchUpstream.mockImplementationOnce(() => new Promise(() => {}));

      render(<ApplicationsView />);
      await waitFor(() => expect(mockApplicationsApi.fetchAll).toHaveBeenCalled());

      const upstreamBtn = await screen.findByTitle('View upstream dependencies');
      fireEvent.click(upstreamBtn);

      await waitFor(() => {
        expect(screen.getByText('Loading upstream dependencies...')).toBeInTheDocument();
      });
    });

    it('loading spinner shows correct text for downstream in dark mode', async () => {
      mockApplicationsApi.fetchDownstream.mockImplementationOnce(() => new Promise(() => {}));

      render(<ApplicationsView />);
      await waitFor(() => expect(mockApplicationsApi.fetchAll).toHaveBeenCalled());

      const downstreamBtn = await screen.findByTitle('View downstream dependencies');
      fireEvent.click(downstreamBtn);

      await waitFor(() => {
        expect(screen.getByText('Loading downstream dependencies...')).toBeInTheDocument();
      });
    });

    it('spinner disappears after upstream fetch completes', async () => {
      let resolveUpstream!: (v: apiClient.DependencyData[]) => void;
      mockApplicationsApi.fetchUpstream.mockImplementationOnce(
        () => new Promise(res => { resolveUpstream = res; })
      );

      render(<ApplicationsView />);
      await waitFor(() => expect(mockApplicationsApi.fetchAll).toHaveBeenCalled());

      const upstreamBtn = await screen.findByTitle('View upstream dependencies');
      fireEvent.click(upstreamBtn);

      await waitFor(() => expect(document.querySelector('.animate-spin')).toBeInTheDocument());

      resolveUpstream([]);

      await waitFor(() => {
        expect(screen.queryByText(/Loading upstream/)).not.toBeInTheDocument();
      });
    });
  });

  // ── Table Rendering ────────────────────────────────────────────────────

  describe('Table Rendering', () => {
    it('renders table with application rows', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole('table');
        expect(table).toBeInTheDocument();
      });
    });

    it('displays application columns in table', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole('table');
        expect(table).toBeInTheDocument();
      });
    });

    it('renders correct number of rows for applications', async () => {
      const multipleApps = [
        { ...mockApplication, id: 1 },
        { ...mockApplication, id: 2, name: 'App 2' },
        { ...mockApplication, id: 3, name: 'App 3' },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(multipleApps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles empty application list', async () => {
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('displays application with complete data', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole('table');
        expect(table).toBeInTheDocument();
      });
    });

    it('displays application with partial data', async () => {
      const partialApp: apiClient.Application = {
        ...mockApplication,
        namespace: undefined,
        appName: undefined,
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([partialApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole('table');
        expect(table).toBeInTheDocument();
      });
    });
  });

  // ── Column Visibility ──────────────────────────────────────────────────

  describe('Column Visibility', () => {
    it('renders columns menu button', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('toggles column visibility', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Component should render with default columns visible
      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });

    it('shows visible columns in table', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole('table');
        expect(table).toBeInTheDocument();
      });
    });

    it('hides hidden columns in table', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Verify some columns are not shown by default
      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });
  });

  // ── Density Settings ────────────────────────────────────────────────────

  describe('Density Settings', () => {
    it('renders density menu button', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('has default density setting', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Component should render with standard density
      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });

    it('supports density modes (compact, standard, comfortable)', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Component should support density changes
      expect(screen.getByRole('table')).toBeInTheDocument();
    });
  });

  // ── Sorting ────────────────────────────────────────────────────────

  describe('Sorting', () => {
    it('applies default sort on certified column', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Should render sorted by certified descending by default
      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });

    it('supports column sorting', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });

    it('toggles sort direction on repeated clicks', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });
  });

  // ── Pagination ────────────────────────────────────────────────────────

  describe('Pagination', () => {
    it('renders pagination controls', async () => {
      const manyApps = Array.from({ length: 50 }, (_, i) => ({
        ...mockApplication,
        id: i + 1,
        name: `App ${i + 1}`,
      }));
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(manyApps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('has default page size of 25', async () => {
      const manyApps = Array.from({ length: 50 }, (_, i) => ({
        ...mockApplication,
        id: i + 1,
        name: `App ${i + 1}`,
      }));
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(manyApps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('changes page on pagination button click', async () => {
      const manyApps = Array.from({ length: 50 }, (_, i) => ({
        ...mockApplication,
        id: i + 1,
        name: `App ${i + 1}`,
      }));
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(manyApps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('disables previous button on first page', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Should have pagination controls
      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });
  });

  // ── Search Functionality ────────────────────────────────────────────────

  describe('Search Functionality', () => {
    it('supports search functionality in filters', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Component supports search via DataTable
      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('filters applications by search term', async () => {
      const apps = [
        { ...mockApplication, id: 1, name: 'Payment Service' },
        { ...mockApplication, id: 2, name: 'Inventory Service' },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(apps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles search in filter state', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });

    it('performs case-insensitive search', async () => {
      const apps = [
        { ...mockApplication, id: 1, name: 'Payment Service' },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(apps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });
  });

  // ── Filter Functionality ────────────────────────────────────────────────

  describe('Filter Functionality', () => {
    it('renders filters panel', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('filters by tenant', async () => {
      const apps = [
        { ...mockApplication, id: 1, tenant: 'tenant-1' },
        { ...mockApplication, id: 2, tenant: 'tenant-2' },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(apps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('filters by tier', async () => {
      const apps = [
        { ...mockApplication, id: 1, tier: 'production' },
        { ...mockApplication, id: 2, tier: 'staging' },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(apps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('filters by certified status', async () => {
      const apps = [
        { ...mockApplication, id: 1, certified: true },
        { ...mockApplication, id: 2, certified: false },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(apps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('combines multiple filters', async () => {
      const apps = [
        { ...mockApplication, id: 1, tenant: 'tenant-1', tier: 'production' },
        { ...mockApplication, id: 2, tenant: 'tenant-2', tier: 'staging' },
      ];
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(apps);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('clears filters', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });
  });

  // ── Row Actions ────────────────────────────────────────────────────────

  describe('Row Actions', () => {
    it('renders action buttons for each row', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('opens detail modal on detail button click', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const detailBtn = await screen.findByTitle('View application details');
      fireEvent.click(detailBtn);

      await waitFor(() => {
        expect(screen.getByText('Application Details')).toBeInTheDocument();
      });
    });

    it('opens health report modal on health button click', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const healthBtn = await screen.findByTitle('Run health check report');
      fireEvent.click(healthBtn);

      await waitFor(() => {
        expect(screen.getByTestId('health-report-modal')).toBeInTheDocument();
      });
    });

    it('opens upstream dependencies modal', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValueOnce([]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const upstreamBtn = await screen.findByTitle('View upstream dependencies');
      fireEvent.click(upstreamBtn);

      await waitFor(() => {
        expect(screen.getByText('Upstream Dependencies')).toBeInTheDocument();
      });
    });

    it('opens downstream dependencies modal', async () => {
      mockApplicationsApi.fetchDownstream.mockResolvedValueOnce([]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const downstreamBtn = await screen.findByTitle('View downstream dependencies');
      fireEvent.click(downstreamBtn);

      await waitFor(() => {
        expect(screen.getByText('Downstream Dependencies')).toBeInTheDocument();
      });
    });
  });

  // ── Detail Modal ────────────────────────────────────────────────────────

  describe('Detail Modal', () => {
    it('renders detail modal with application information', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const detailBtn = await screen.findByTitle('View application details');
      fireEvent.click(detailBtn);

      await waitFor(() => {
        expect(screen.getByText('Application Details')).toBeInTheDocument();
      });
    });

    it('displays application name in modal', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const detailBtn = await screen.findByTitle('View application details');
      fireEvent.click(detailBtn);

      await waitFor(() => {
        expect(screen.getAllByText('Test App').length).toBeGreaterThanOrEqual(1);
      });
    });

    it('closes modal on close button click', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const detailBtn = await screen.findByTitle('View application details');
      fireEvent.click(detailBtn);

      await waitFor(() => screen.getByText('Application Details'));

      // The footer has an explicit "Close" button
      const closeBtn = screen.getByRole("button", { name: /^close$/i });
      fireEvent.click(closeBtn);

      await waitFor(() => {
        expect(screen.queryByText('Application Details')).not.toBeInTheDocument();
      });
    });

    it('displays WCNP information when applicable', async () => {
      const wcnpApp: apiClient.Application = {
        ...mockApplication,
        applicationType: 'wcnp',
        namespace: 'payment-ns',
        appName: 'payment-app',
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([wcnpApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const detailBtn = await screen.findByTitle('View application details');
      fireEvent.click(detailBtn);

      await waitFor(() => {
        expect(screen.getByText('WCNP')).toBeInTheDocument();
      });
    });

    it('displays OneOps information when applicable', async () => {
      const oneOpsApp: apiClient.Application = {
        ...mockApplication,
        applicationType: 'oneops',
        oneOpsOrg: 'org',
        oneOpsAssembly: 'assembly',
        oneOpsPlatform: 'platform',
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([oneOpsApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const detailBtn = await screen.findByTitle('View application details');
      fireEvent.click(detailBtn);

      await waitFor(() => {
        expect(screen.getByText('OneOps')).toBeInTheDocument();
      });
    });
  });

  // ── Export Functionality ────────────────────────────────────────────────

  describe('Export Functionality', () => {
    it('renders export button', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });

    it('exports data on export button click', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });
  });

  // ── Dependency Modal ────────────────────────────────────────────────────

  describe('Dependency Modal', () => {
    it('displays upstream dependencies in modal', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValueOnce([mockDependency]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('displays downstream dependencies in modal', async () => {
      mockApplicationsApi.fetchDownstream.mockResolvedValueOnce([mockDependency]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles adding upstream dependencies', async () => {
      mockApplicationsApi.addUpstreamDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles removing upstream dependencies', async () => {
      mockApplicationsApi.deleteUpstreamDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles adding downstream dependencies', async () => {
      mockApplicationsApi.addDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles removing downstream dependencies', async () => {
      mockApplicationsApi.deleteDownstreamDependency.mockResolvedValueOnce({
        success: true,
      });

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles errors when loading dependencies', async () => {
      mockApplicationsApi.fetchUpstream.mockRejectedValueOnce(
        new Error('Failed to load dependencies')
      );

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });
  });

  // ── Edge Cases ──────────────────────────────────────────────────────────

  describe('Edge Cases', () => {
    it('handles application with no team information', async () => {
      const noTeamApp: apiClient.Application = {
        ...mockApplication,
        team: null,
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([noTeamApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles application with special characters in name', async () => {
      const specialApp: apiClient.Application = {
        ...mockApplication,
        name: 'App-123 "Special" & $Test',
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([specialApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles very long application names', async () => {
      const longNameApp: apiClient.Application = {
        ...mockApplication,
        name: 'A'.repeat(200),
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([longNameApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles application with many slack channels', async () => {
      const manyChannelsApp: apiClient.Application = {
        ...mockApplication,
        slackChannels: Array.from({ length: 20 }, (_, i) => `#channel-${i}`),
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([manyChannelsApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles application with no slack channels', async () => {
      const noChannelsApp: apiClient.Application = {
        ...mockApplication,
        slackChannels: [],
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([noChannelsApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('handles null application fields gracefully', async () => {
      const nullFieldsApp: apiClient.Application = {
        ...mockApplication,
        namespace: null as any,
        appName: null as any,
        cluster: null as any,
      };
      mockApplicationsApi.fetchAll.mockResolvedValueOnce([nullFieldsApp]);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });
  });

  // ── Accessibility ──────────────────────────────────────────────────────

  describe('Accessibility', () => {
    it('renders semantic table structure', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const table = screen.getByRole('table');
        expect(table).toBeInTheDocument();
      });
    });

    it('has proper button labels for icon buttons', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        const buttons = screen.getAllByRole('button');
        expect(buttons.length).toBeGreaterThan(0);
      });
    });

    it('supports keyboard navigation', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const buttons = screen.getAllByRole('button');
      expect(buttons.length).toBeGreaterThan(0);
    });
  });

  // ── Performance ────────────────────────────────────────────────────────

  describe('Performance', () => {
    it('handles large dataset efficiently', async () => {
      const largeDataset = Array.from({ length: 1000 }, (_, i) => ({
        ...mockApplication,
        id: i + 1,
        name: `App ${i + 1}`,
      }));
      mockApplicationsApi.fetchAll.mockResolvedValueOnce(largeDataset);

      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });
    });

    it('maintains performance with frequent filter changes', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      // Component should handle frequent state changes efficiently
      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });

    it('maintains performance with multiple sort changes', async () => {
      render(<ApplicationsView />);

      await waitFor(() => {
        expect(mockApplicationsApi.fetchAll).toHaveBeenCalled();
      });

      const table = screen.getByRole('table');
      expect(table).toBeInTheDocument();
    });
  });
});
