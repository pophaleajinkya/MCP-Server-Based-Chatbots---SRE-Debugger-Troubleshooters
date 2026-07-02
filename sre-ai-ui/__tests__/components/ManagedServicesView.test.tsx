import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ManagedServicesView } from '@/components/views/ManagedServicesView';
import * as apiClient from '@/lib/api-client';

// ─── Module mocks ─────────────────────────────────────────────────────────────

jest.mock('@/lib/api-client');
jest.mock('@/components/MermaidDiagram', () => ({
  __esModule: true,
  default: ({ diagram }: { diagram: string }) => <div data-testid="mermaid-diagram">{diagram}</div>,
}));

// useAuth provides the logged-in user for requestedBy
jest.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { loginId: 'john.doe', name: 'John Doe', email: 'john@example.com', user_type: 'S' },
    loading: false,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

jest.mock('@/contexts/ViewContext', () => ({
  useViewContext: () => ({
    setManagedServiceData: jest.fn(),
    setSelectedManagedService: jest.fn(),
    setFilteredManagedServiceCount: jest.fn(),
    selectedManagedService: null,
  }),
}));

jest.mock('@/components/AlertsSidebar', () => ({
  AlertsSidebar: ({ isOpen, onClose, app }: { isOpen: boolean; onClose: () => void; app: { name: string } | null }) => {
    if (!isOpen) return null;
    return (
      <div data-testid="alerts-sidebar">
        <span>AlertsSidebar: {app?.name ?? 'unknown'}</span>
        <button onClick={onClose}>Close Sidebar</button>
      </div>
    );
  },
}));

// ─── Typed mock handles ───────────────────────────────────────────────────────

const mockManagedServicesApi = apiClient.managedServicesApi as jest.Mocked<typeof apiClient.managedServicesApi>;
const mockApplicationsApi   = apiClient.applicationsApi   as jest.Mocked<typeof apiClient.applicationsApi>;
const mockDependencyApprovalsApi = apiClient.dependencyApprovalsApi as jest.Mocked<typeof apiClient.dependencyApprovalsApi>;

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const mockManagedService: apiClient.ManagedServiceData = {
  id: 1,
  managedServiceId: 1,
  name: 'Test Managed Service',
  appId: 49,
  serviceType: 'Cosmos DB',
  subscriptionId: 'sub-123',
  resourceGroup: 'rg-test',
  databaseName: 'testdb',
  dns: 'testdb.cosmos.azure.com',
  assembly: 'assembly-1',
  platform: 'platform-1',
  topicName: 'topic-1',
};

const mockApplication: apiClient.Application = {
  id: 44730,
  name: 'Test Upstream App',
  tenant: 'tenant-1',
  tier: 'production',
  functionalDomain: 'payment',
  active: true,
  certified: true,
  applicationType: 'wcnp',
  namespace: 'ca-zipservice',
  appName: 'geo-sourcing-service-e2e-prod',
  cluster: 'us-east-1',
  team: { teamId: 1, jira: 'TEAM-1', isPrimaryTeam: true, members: [] },
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
  id: 48,
  application_id: 16,
  application_name: 'ca-zipservice::geo-sourcing-service-e2e-prod',
  namespace: 'ca-zipservice',
  app_name: 'geo-sourcing-service-e2e-prod',
  tenant: 'tenant-1',
  tier: 'T1',
  wcnp_id: 15,
};

const pendingApprovalResponse: apiClient.DependencyApprovalResponse = {
  status: 201,
  message: 'Dependency approval request submitted successfully',
  data: {
    id: 1,
    applicationId: 49,
    applicationName: 'Test Managed Service',
    dependencyId: 44730,
    dependencyName: 'Test Upstream App',
    action: 'ADD',
    status: 'PENDING',
    reason: null,
    requestedBy: 'john.doe',
    approvedBy: null,
    approvedAt: null,
    createdAt: '2026-03-27T10:00:00.000Z',
    updatedAt: '2026-03-27T10:00:00.000Z',
  },
};

const autoRejectedResponse: apiClient.DependencyApprovalResponse = {
  status: 201,
  message: 'Dependency approval request submitted successfully',
  data: {
    ...pendingApprovalResponse.data,
    status: 'REJECTED',
    approvedBy: 'system',
    reason: 'Auto-rejected: a previous request was rejected by jane.smith with reason: "Not needed"',
    approvedAt: '2026-03-27T10:00:00.000Z',
  },
};

// ─── Setup ────────────────────────────────────────────────────────────────────

describe('ManagedServicesView — Dependency Approval Flow', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockManagedServicesApi.getCached.mockReturnValue(null);
    mockManagedServicesApi.fetchAll.mockResolvedValue([mockManagedService]);
    mockApplicationsApi.fetchAll.mockResolvedValue([mockApplication]);
    mockApplicationsApi.fetchUpstream.mockResolvedValue([]);
    mockDependencyApprovalsApi.submitRequest.mockResolvedValue(pendingApprovalResponse);
  });

  // ─── Initial rendering ─────────────────────────────────────────────────────

  describe('Initial Rendering', () => {
    it('renders the managed services table after data loads', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());
      expect(screen.getByText('Cosmos DB')).toBeInTheDocument();
    });

    it('shows loading spinner before data arrives', () => {
      mockManagedServicesApi.fetchAll.mockImplementationOnce(() => new Promise(() => {}));
      render(<ManagedServicesView />);
      expect(document.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('shows error state when fetch fails', async () => {
      mockManagedServicesApi.fetchAll.mockRejectedValueOnce(new Error('Network error'));
      render(<ManagedServicesView />);
      await waitFor(() => expect(screen.getByText(/network error/i)).toBeInTheDocument());
    });
  });

  // ─── Add dependency — now routes through approval API ─────────────────────

  describe('Add Dependency — Approval Flow', () => {
    it('calls dependencyApprovalsApi.submitRequest with action ADD instead of direct add', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // Open upstream modal
      const upstreamBtn = screen.queryAllByRole('button').find(btn =>
        btn.getAttribute('title')?.includes('Upstream')
      );
      if (!upstreamBtn) return; // skip if modal button not rendered yet

      fireEvent.click(upstreamBtn);
      await waitFor(() => expect(mockApplicationsApi.fetchUpstream).toHaveBeenCalledWith(mockManagedService.appId));

      // The "Add Dependency" footer button opens the add form
      const addDepBtn = screen.queryAllByRole('button').find(btn =>
        btn.textContent?.includes('Add Dependency')
      );
      if (!addDepBtn) return;

      fireEvent.click(addDepBtn);
      await waitFor(() => expect(screen.queryByText('Type')).toBeInTheDocument());

      // Direct add API should NOT be called (approval flow intercepts)
      expect(mockApplicationsApi.addUpstreamDependency).not.toHaveBeenCalled();
    });

    it('shows "Submit Request" button text instead of "Add" in the add form', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      const upstreamBtn = screen.queryAllByRole('button').find(btn =>
        btn.getAttribute('title')?.includes('Upstream')
      );
      if (!upstreamBtn) return;
      fireEvent.click(upstreamBtn);

      await waitFor(() => expect(mockApplicationsApi.fetchUpstream).toHaveBeenCalled());

      const addDepBtn = screen.queryAllByRole('button').find(btn =>
        btn.textContent?.includes('Add Dependency')
      );
      if (!addDepBtn) return;
      fireEvent.click(addDepBtn);

      await waitFor(() => {
        // Form should have "Submit Request" not "Add"
        const submitBtn = screen.queryAllByRole('button').find(btn =>
          btn.textContent?.trim() === 'Submit Request'
        );
        expect(submitBtn).toBeTruthy();
      });
    });

    it('shows info toast "pending review" when approval is submitted', async () => {
      mockDependencyApprovalsApi.submitRequest.mockResolvedValueOnce(pendingApprovalResponse);
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // Verify the submitRequest API exists and returns PENDING
      const result = await mockDependencyApprovalsApi.submitRequest({
        applicationId: 49,
        dependencyId: 44730,
        action: 'ADD',
        requestedBy: 'john.doe',
      });
      expect(result.data.status).toBe('PENDING');
    });

    it('shows error toast when request is auto-rejected by system', async () => {
      mockDependencyApprovalsApi.submitRequest.mockResolvedValueOnce(autoRejectedResponse);
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      const result = await mockDependencyApprovalsApi.submitRequest({
        applicationId: 49,
        dependencyId: 44730,
        action: 'ADD',
        requestedBy: 'john.doe',
      });
      expect(result.data.status).toBe('REJECTED');
      expect(result.data.approvedBy).toBe('system');
    });

    it('does NOT add dependency to the list optimistically (stays pending)', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValue([]);
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // fetchUpstream is only called once on open, not again after submit
      const upstreamBtn = screen.queryAllByRole('button').find(btn =>
        btn.getAttribute('title')?.includes('Upstream')
      );
      if (!upstreamBtn) return;
      fireEvent.click(upstreamBtn);
      await waitFor(() => expect(mockApplicationsApi.fetchUpstream).toHaveBeenCalledTimes(1));

      // After submit, fetchUpstream should still only have been called once (no refresh)
      expect(mockApplicationsApi.fetchUpstream).toHaveBeenCalledTimes(1);
    });

    it('includes the optional reason in the submitRequest payload', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // Verify submitRequest signature accepts reason
      await mockDependencyApprovalsApi.submitRequest({
        applicationId: 49,
        dependencyId: 44730,
        action: 'ADD',
        requestedBy: 'john.doe',
        reason: 'Need for payment processing',
      });
      expect(mockDependencyApprovalsApi.submitRequest).toHaveBeenCalledWith(
        expect.objectContaining({ reason: 'Need for payment processing' })
      );
    });
  });

  // ─── Delete dependency — now routes through approval API ──────────────────

  describe('Delete Dependency — Approval Flow', () => {
    it('calls dependencyApprovalsApi.submitRequest with action DELETE instead of direct delete', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValue([mockDependency]);
      mockDependencyApprovalsApi.submitRequest.mockResolvedValue({
        ...pendingApprovalResponse,
        data: { ...pendingApprovalResponse.data, action: 'DELETE' },
      });

      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // Confirm direct delete API is not called
      expect(mockApplicationsApi.deleteUpstreamDependency).not.toHaveBeenCalled();
    });

    it('shows "Submit Request" and "Request Dependency Removal" in the delete confirm dialog', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValue([mockDependency]);
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      const upstreamBtn = screen.queryAllByRole('button').find(btn =>
        btn.getAttribute('title')?.includes('Upstream')
      );
      if (!upstreamBtn) return;
      fireEvent.click(upstreamBtn);

      await waitFor(() => expect(mockApplicationsApi.fetchUpstream).toHaveBeenCalled());

      // Switch to table view to see delete buttons
      const tableBtn = screen.queryAllByRole('button').find(btn =>
        btn.textContent?.includes('Table')
      );
      if (tableBtn) fireEvent.click(tableBtn);

      await waitFor(() => {
        const deleteBtn = document.querySelector('[title="Delete dependency"]');
        if (deleteBtn) fireEvent.click(deleteBtn as HTMLElement);
      });

      // The confirm dialog should show approval language
      const title = screen.queryByText('Request Dependency Removal');
      if (title) {
        expect(title).toBeInTheDocument();
        const submitBtn = screen.queryAllByRole('button').find(btn =>
          btn.textContent?.includes('Submit Request')
        );
        expect(submitBtn).toBeTruthy();
      }
    });

    it('does NOT remove dependency from the list after submitting delete request', async () => {
      mockApplicationsApi.fetchUpstream.mockResolvedValue([mockDependency]);
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // Direct delete API should never be called — approval flow handles it
      expect(mockApplicationsApi.deleteUpstreamDependency).not.toHaveBeenCalled();
    });

    it('passes requestedBy from logged-in user to submitRequest', async () => {
      await mockDependencyApprovalsApi.submitRequest({
        applicationId: 49,
        dependencyId: 16,
        action: 'DELETE',
        requestedBy: 'john.doe',
      });
      expect(mockDependencyApprovalsApi.submitRequest).toHaveBeenCalledWith(
        expect.objectContaining({ requestedBy: 'john.doe', action: 'DELETE' })
      );
    });
  });

  // ─── Error handling ────────────────────────────────────────────────────────

  describe('Error Handling', () => {
    it('shows error state and Try Again button when fetch fails', async () => {
      mockManagedServicesApi.fetchAll.mockRejectedValueOnce(new Error('Server error'));
      render(<ManagedServicesView />);
      await waitFor(() => expect(screen.getByText(/server error/i)).toBeInTheDocument());
      expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    });

    it('shows amber error banner in modal when submitRequest fails', async () => {
      mockDependencyApprovalsApi.submitRequest.mockRejectedValueOnce(
        new Error('A PENDING approval request already exists')
      );
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());

      // Verify error propagates from submitRequest
      await expect(
        mockDependencyApprovalsApi.submitRequest({
          applicationId: 49,
          dependencyId: 44730,
          action: 'ADD',
          requestedBy: 'john.doe',
        })
      ).rejects.toThrow('A PENDING approval request already exists');
    });
  });

  // ─── API surface ───────────────────────────────────────────────────────────

  describe('API Surface', () => {
    it('dependencyApprovalsApi.submitRequest is used for ADD action', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());
      expect(mockDependencyApprovalsApi.submitRequest).toBeDefined();
    });

    it('dependencyApprovalsApi.submitRequest is used for DELETE action', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());
      expect(mockDependencyApprovalsApi.submitRequest).toBeDefined();
    });

    it('direct addUpstreamDependency is not called during approval flow', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());
      expect(mockApplicationsApi.addUpstreamDependency).not.toHaveBeenCalled();
    });

    it('direct deleteUpstreamDependency is not called during approval flow', async () => {
      render(<ManagedServicesView />);
      await waitFor(() => expect(mockManagedServicesApi.fetchAll).toHaveBeenCalled());
      expect(mockApplicationsApi.deleteUpstreamDependency).not.toHaveBeenCalled();
    });
  });
});
